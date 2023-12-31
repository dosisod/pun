import libcst as cst

from pun.main import MatchDowngrader


def test_matches() -> None:
    code = """\
match 1:
    case True:
        pass
    case False:
        pass
    case None:
        pass
    case int(x):
        pass
    case int(_):
        pass
    case int():
        pass
    case int(x) if x % 2 == 0:
        pass
    case x if x % 2 == 1:
        pass
    case 1 as x:
        pass
    case int() as x:
        pass
    case C():
        pass
    case C(1):
        pass
    case C(1, 2):
        pass
    case C(x=1):
        pass
    case 1 | 2 | 3:
        pass
    case _:
        pass
""".strip()

    expected = """
__match_subject = 1
if __match_subject is True:
    pass
elif __match_subject is False:
    pass
elif __match_subject is None:
    pass
elif isinstance(__match_subject, int) and (True, (x := __match_subject))[0]:
    pass
elif isinstance(__match_subject, int):
    pass
elif isinstance(__match_subject, int):
    pass
elif isinstance(__match_subject, int) and (True, (x := __match_subject))[0] and (x % 2 == 0):
    pass
elif (True, (x := __match_subject))[0] and (x % 2 == 1):
    pass
elif (__match_subject == 1, (x := __match_subject))[0]:
    pass
elif (isinstance(__match_subject, int), (x := __match_subject))[0]:
    pass
elif isinstance(__match_subject, C):
    pass
elif isinstance(__match_subject, C) and (__match_args := getattr(__match_subject, "__match_args__", None)) and isinstance(__match_args, tuple) and (len(__match_args) >= 1) and hasattr(__match_subject, __match_args[0]) and (__match_subject1 := getattr(__match_subject, __match_args[0])) and (__match_subject1 == 1):
    pass
elif isinstance(__match_subject, C) and (__match_args := getattr(__match_subject, "__match_args__", None)) and isinstance(__match_args, tuple) and (len(__match_args) >= 2) and hasattr(__match_subject, __match_args[0]) and (__match_subject1 := getattr(__match_subject, __match_args[0])) and (__match_subject1 == 1) and hasattr(__match_subject, __match_args[1]) and (__match_subject2 := getattr(__match_subject, __match_args[1])) and (__match_subject2 == 2):
    pass
elif isinstance(__match_subject, C) and hasattr(__match_subject, "x") and (__match_subject1 := getattr(__match_subject, "x")) and (__match_subject1 == 1):
    pass
elif (__match_subject == 1) or (__match_subject == 2) or (__match_subject == 3):
    pass
elif True:
    pass
""".strip()

    match = cst.parse_module(code)

    stmts = match.visit(MatchDowngrader())

    assert stmts.code == expected
