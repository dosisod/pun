import sys
from collections.abc import Sequence
from importlib.machinery import ModuleSpec
from importlib.util import find_spec
from itertools import count
from pathlib import Path
from typing import cast

import libcst as cst

STDLIB_MODULE_PREFIXES = tuple(f"{x}." for x in sys.stdlib_module_names)


class MatchDowngrader(cst.CSTTransformer):
    condition: cst.BaseExpression | None

    def __init__(self) -> None:
        self.counter = count(1)
        self.condition = None

        self.subject_stack = [cst.Name("__match_subject")]
        self.ifs: list[cst.If] = []
        self.ignored_nodes = set[int]()

    @property
    def subject(self) -> cst.Name:
        return self.subject_stack[-1]

    def new_subject(self) -> cst.Name:
        i = next(self.counter)

        subject = cst.Name(f"__match_subject{i}")

        self.subject_stack.append(subject)

        return subject

    def visit_MatchCase(self, node: cst.MatchCase) -> None:
        # reset counter because previous counters are only scoped to above case
        self.counter = count(1)
        self.condition = None

    def leave_MatchCase(
        self, original_node: cst.MatchCase, updated_node: cst.MatchCase
    ) -> cst.MatchCase:
        assert self.condition

        if updated_node.guard:
            self.condition = self.make_and_expr(self.condition, updated_node.guard)

        self.ifs.append(
            cst.If(
                test=self.condition,
                body=cst.IndentedBlock(body=updated_node.body.body),  # type: ignore
            )
        )

        return updated_node

    def leave_MatchSingleton(
        self, original_node: cst.MatchSingleton, updated_node: cst.MatchSingleton
    ) -> cst.MatchPattern:
        condition = cst.Comparison(
            left=self.subject,
            comparisons=[
                cst.ComparisonTarget(operator=cst.Is(), comparator=updated_node.value),
            ],
        )

        if self.condition:
            self.condition = self.make_and_expr(self.condition, condition)
        else:
            self.condition = condition

        return updated_node

    def leave_MatchValue(
        self, original_node: cst.MatchValue, updated_node: cst.MatchValue
    ) -> cst.MatchPattern:
        condition = cst.Comparison(
            left=self.subject,
            comparisons=[
                cst.ComparisonTarget(operator=cst.Equal(), comparator=updated_node.value),
            ],
        )

        if self.condition:
            self.condition = self.make_and_expr(self.condition, condition)
        else:
            self.condition = condition

        return updated_node

    def leave_MatchAs(
        self, original_node: cst.MatchAs, updated_node: cst.MatchAs
    ) -> cst.MatchPattern:
        # case ... as x:
        if updated_node.pattern and updated_node.name:
            alias = cst.NamedExpr(
                lpar=[cst.LeftParen()],
                target=updated_node.name,
                value=self.subject,
                rpar=[cst.RightParen()],
            )

            assert self.condition

            self.condition = cst.Subscript(
                value=cst.Tuple(elements=[cst.Element(self.condition), cst.Element(alias)]),
                slice=[cst.SubscriptElement(slice=cst.Index(value=cst.Integer(value="0")))],
            )

        # case _:
        elif not updated_node.pattern and not updated_node.name:
            if not self.condition:
                self.condition = cst.Name("True")

        # case x:
        elif not updated_node.pattern and updated_node.name:
            alias = cst.NamedExpr(
                lpar=[cst.LeftParen()],
                target=updated_node.name,
                value=self.subject,
                rpar=[cst.RightParen()],
            )

            condition = cst.Subscript(
                value=cst.Tuple(elements=[cst.Element(cst.Name("True")), cst.Element(alias)]),
                slice=[cst.SubscriptElement(slice=cst.Index(value=cst.Integer(value="0")))],
            )

            if self.condition:
                self.condition = self.make_and_expr(self.condition, condition)
            else:
                self.condition = condition

        return updated_node

    def visit_MatchClass(self, node: cst.MatchClass) -> None:
        isinstance_check = cst.Call(
            func=cst.Name("isinstance"),
            args=[cst.Arg(self.subject), cst.Arg(node.cls)],
        )

        if self.condition:
            self.condition = self.make_and_expr(self.condition, isinstance_check)
        else:
            self.condition = isinstance_check

        match node.cls:
            # special case for built-ins, don't need to do as many checks
            # TODO: add all built-in classes
            case cst.Name(value="int" | "str" | "float"):
                assert 0 <= len(node.patterns) <= 1

                assert not node.kwds

                return

        # pattern contains positional args, need to setup __match_args__ so that child patterns
        # can access the values.
        if node.patterns:
            match_args = cst.Name("__match_args")

            get_match_args = cst.Call(
                func=cst.Name("getattr"),
                args=[
                    cst.Arg(self.subject),
                    cst.Arg(cst.SimpleString('"__match_args__"')),
                    cst.Arg(cst.Name("None")),
                ],
            )

            self.condition = self.make_and_expr(
                self.condition, cst.NamedExpr(target=match_args, value=get_match_args)
            )

            tuple_check = cst.Call(
                func=cst.Name("isinstance"),
                args=[cst.Arg(match_args), cst.Arg(cst.Name("tuple"))],
            )

            self.condition = self.make_and_expr(self.condition, tuple_check)

            len_call = cst.Call(func=cst.Name("len"), args=[cst.Arg(match_args)])

            len_check = cst.Comparison(
                left=len_call,
                comparisons=[
                    cst.ComparisonTarget(
                        operator=cst.GreaterThanEqual(),
                        comparator=cst.Integer(str(len(node.patterns))),
                    ),
                ],
            )

            self.condition = self.make_and_expr(self.condition, len_check)

            for i, positional in enumerate(node.patterns):
                match_arg = cst.Subscript(
                    value=match_args,
                    slice=[cst.SubscriptElement(cst.Index(value=cst.Integer(value=str(i))))],
                )

                hasattr_check = cst.Call(
                    func=cst.Name("hasattr"),
                    args=[cst.Arg(self.subject), cst.Arg(match_arg)],
                )

                self.condition = self.make_and_expr(self.condition, hasattr_check)

                class_subject = self.subject

                getattr_alias = cst.NamedExpr(
                    target=self.new_subject(),
                    value=cst.Call(
                        func=cst.Name("getattr"),
                        args=[cst.Arg(class_subject), cst.Arg(match_arg)],
                    ),
                )

                self.condition = self.make_and_expr(self.condition, getattr_alias)

                positional.visit(self)
                self.ignored_nodes.add(id(positional))

                # TODO: make this more ergonomic
                self.subject_stack.pop()

        if node.kwds:
            for kw in node.kwds:
                key_name = cst.SimpleString(f'"{kw.key.value}"')

                hasattr_check = cst.Call(
                    func=cst.Name("hasattr"),
                    args=[cst.Arg(self.subject), cst.Arg(key_name)],
                )

                self.condition = self.make_and_expr(self.condition, hasattr_check)

                class_subject = self.subject

                # TODO: replace getattr(x, y) with x.y
                getattr_alias = cst.NamedExpr(
                    target=self.new_subject(),
                    value=cst.Call(
                        func=cst.Name("getattr"),
                        args=[cst.Arg(class_subject), cst.Arg(key_name)],
                    ),
                )

                self.condition = self.make_and_expr(self.condition, getattr_alias)

                kw.visit(self)
                self.ignored_nodes.add(id(kw))

                # TODO: make this more ergonomic
                self.subject_stack.pop()

    def visit_MatchSequenceElement(self, node: cst.MatchSequenceElement) -> bool:
        if id(node) in self.ignored_nodes:
            return False

        return True

    def visit_MatchKeywordElement(self, node: cst.MatchKeywordElement) -> bool:
        if id(node) in self.ignored_nodes:
            return False

        return True

    def leave_Match(  # type: ignore[override]
        self, original_node: cst.Match, updated_node: cst.Match
    ) -> cst.FlattenSentinel[cst.CSTNode]:
        # evaluate the match subject and store it in a special variable
        subject_assign = cst.Assign(
            targets=[cst.AssignTarget(target=self.subject)],
            value=updated_node.subject,
        )

        assert self.ifs

        return cst.FlattenSentinel(
            (
                cst.SimpleStatementLine(body=[subject_assign]),
                self.treeify_if_nodes(self.ifs),
            )
        )

    @staticmethod
    def treeify_if_nodes(ifs: Sequence[cst.If]) -> cst.If:
        """
        Convert a list of If nodes into a single If node.
        """

        done = ifs[-1]

        for _if in reversed(ifs[:-1]):
            done = _if.with_changes(orelse=done)

        return done

    # TODO: give this a better name
    def make_and_expr(
        self, lhs: cst.BaseExpression, rhs: cst.BaseExpression
    ) -> cst.BaseExpression:
        return cst.BooleanOperation(
            left=self.parenthesize(lhs, only_when_needed=True),
            operator=cst.And(),
            right=self.parenthesize(rhs, only_when_needed=True),
        )

    @staticmethod
    def parenthesize(
        expr: cst.BaseExpression, *, only_when_needed: bool = False
    ) -> cst.BaseExpression:
        if only_when_needed:
            if expr.lpar:
                return expr

            match expr:
                case cst.Call() | cst.Subscript() | cst.BooleanOperation(operator=cst.And()):
                    return expr

        return expr.with_changes(lpar=[cst.LeftParen()], rpar=[cst.RightParen()])


class BundlerTransformer(cst.CSTTransformer):
    def __init__(
        self, project_root: Path, package: str, loaded_files: set[Path] | None = None
    ) -> None:
        super().__init__()

        self.project_root = project_root
        self.package = package
        self.future_imports = set[str]()
        self.is_top_level_module = True
        self.loaded_files = loaded_files or set()

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        stmts = []

        for stmt in updated_node.body:
            if isinstance(stmt, cst.SimpleStatementLine):
                if isinstance(stmt.body[0], cst.Module):
                    mod = stmt.body[0]

                    if isinstance(mod.body, cst.BaseSuite):
                        new_stmts = list(mod.body.body)
                    else:
                        new_stmts = list(mod.body)

                    if new_stmts:
                        if mod.header:
                            new_stmts[0] = new_stmts[0].with_changes(leading_lines=mod.header)

                        if mod.footer:
                            new_stmts.append(cst.EmptyLine(comment=mod.footer[0].comment))

                    stmts.extend(new_stmts)

                else:
                    stmts.append(stmt)

            else:
                stmts.append(stmt)

        if self.is_top_level_module and self.future_imports:
            imports = cst.ImportFrom(
                module=cst.Name(value="__future__"),
                names=[cst.ImportAlias(name=cst.Name(value=x)) for x in self.future_imports],
            )

            stmts = [imports, cst.Newline(), cst.Newline(), *stmts]

        return updated_node.with_changes(body=stmts)

    def leave_Import(
        self, original_node: cst.Import, updated_node: cst.Import
    ) -> cst.Import | cst.RemovalSentinel:
        assert len(updated_node.names) == 1

        name = updated_node.names[0].name.value
        assert isinstance(name, str)

        spec = find_spec(name)
        assert spec

        if self.is_stdlib_spec(spec):
            return updated_node

        return cst.RemoveFromParent()

    def leave_ImportFrom(  # type: ignore[override]  # noqa: PLR0914
        self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom
    ) -> cst.RemovalSentinel | cst.ImportFrom | cst.Module:
        module = updated_node.module
        assert module

        module_name = self.get_string_name(module)

        if module_name == "__future__":
            assert not isinstance(updated_node.names, cst.ImportStar)

            for name in updated_node.names:
                assert not name.asname

                self.future_imports.add(self.get_string_name(name.name))

                return cst.RemoveFromParent()

        as_aliases: dict[str, str] = {}

        if not isinstance(updated_node.names, cst.ImportStar):
            for imported in updated_node.names:
                if imported.asname:
                    old_name = self.get_string_name(imported.name)

                    new_name = imported.asname.name
                    assert isinstance(new_name, cst.Name)

                    as_aliases[old_name] = new_name.value

        module_name = ("." * len(updated_node.relative)) + module_name

        spec = find_spec(module_name, package=self.package)
        assert spec
        assert spec.origin

        if self.is_stdlib_spec(spec):
            return updated_node

        file = Path(spec.origin).resolve()

        if file in self.loaded_files:
            return cst.RemoveFromParent()

        self.loaded_files.add(file)

        new_package = filename_to_package(cwd, file)
        nested_bundler = BundlerTransformer(
            self.project_root, new_package, loaded_files=self.loaded_files
        )
        nested_bundler.is_top_level_module = False

        parsed_module = cst.parse_module(file.read_text())
        bundled_package = parsed_module.visit(nested_bundler)

        self.future_imports |= nested_bundler.future_imports

        if as_aliases:
            aliases_block = []

            for old, new in as_aliases.items():
                comment = cst.EmptyLine(
                    comment=cst.Comment(value=f"# pun: adding import alias {old} -> {new}")
                )

                alias = cst.Assign(
                    targets=[cst.AssignTarget(target=cst.Name(old))],
                    value=cst.Name(new),
                )

                aliases_block.append(
                    cst.SimpleStatementLine(
                        body=[alias],
                        leading_lines=[comment],
                    )
                )

            body = [*bundled_package.body, *aliases_block]

        else:
            body = bundled_package.body  # type: ignore

        start_comment = cst.Comment(value=f"# pun: inlining {module_name}")
        end_comment = cst.Comment(value=f"# pun: done inlining {module_name}")

        return bundled_package.with_changes(
            header=[cst.Newline(), cst.EmptyLine(comment=start_comment)],
            footer=[cst.EmptyLine(comment=end_comment)],
            body=body,
        )

    def leave_Match(  # type: ignore[override]  # noqa: PLR6301
        self, original_node: cst.Match, updated_node: cst.Match
    ) -> cst.FlattenSentinel[cst.CSTNode]:
        return cast(cst.FlattenSentinel[cst.CSTNode], updated_node.visit(MatchDowngrader()))

    def get_string_name(self, node: cst.CSTNode) -> str:
        if isinstance(node, cst.Name):
            return node.value

        if isinstance(node, cst.Attribute):
            lhs = self.get_string_name(node.value)
            rhs = self.get_string_name(node.attr)

            return f"{lhs}.{rhs}"

        assert False  # pragma: no cover

    @staticmethod
    def is_stdlib_spec(spec: ModuleSpec) -> bool:
        # TODO: ignore 3rd party packages as well
        return spec.origin == "built-in" or f"{spec.name}.".startswith(STDLIB_MODULE_PREFIXES)


def filename_to_package(root: Path, filename: Path) -> str:
    file = filename.relative_to(root)

    return ".".join(file.parent.parts)


if __name__ == "__main__":
    cwd = Path.cwd()
    sys.path.append(str(cwd))

    file = Path(sys.argv[1]).resolve()
    package = filename_to_package(cwd, file)

    ast = cst.parse_module(file.read_text())

    transformed = ast.visit(BundlerTransformer(cwd, package))

    print(transformed.code)  # noqa: T201
