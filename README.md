# Pun

A Python bundler.

> Pun is under active development, expect bugs and crashes!

## Why?

For the most part, you don't need to worry about bundling/minifying/polyfilling your Python code like you
would with a language like JavaScript. In certain scenarios though, having the ability to bundle your Python code
can be quite helpful.

Here are a few examples of what Pun could be used for:

* Creating single-file versions of multi-module projects
* Porting Python projects to different platforms such as PyScript, Pyodide, or MicroPython
* Downgrading/back-porting Python projects to older versions of Python
* Easier static analysis, including better dead code elimination
* And much more

## How?

When Pun sees a first-party `import` statement it will inline the contents of that file. Builtin imports
are ignored, and third-party imports are not yet supported.

Additionally, Pun will convert all `match` statements to their equivalent `if` statements. This feature is
always enabled, though future versions of Pun will make this opt-in.
