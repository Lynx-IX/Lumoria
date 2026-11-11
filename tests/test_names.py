"""Every name the code reads is defined somewhere: catches a missing import (like MOD_OFF in ui.py, which crashed
the app when an effect's music note was clicked off) without running the interface. Coarse on purpose: a name
bound anywhere in the module counts as defined, so this only flags names that exist nowhere in it."""
import ast
import builtins
import importlib
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULES = ["app", "ui", "effects", "effects3d", "audio", "tempo", "midi", "shared", "sources", "segment", "recorder",
           "lookcheck"]


def bound_names(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            names.add(node.name)
    return names


class NamesDefined(unittest.TestCase):
    def test_no_undefined_names(self):
        for mod in MODULES:
            path = os.path.join(HERE, mod + ".py")
            if not os.path.exists(path):
                continue
            with self.subTest(module=mod):
                with open(path, encoding="utf8") as fh:
                    tree = ast.parse(fh.read())
                known = bound_names(tree) | set(dir(builtins)) | {"__file__", "__name__", "__doc__"}
                # names a module sets up at import time (ui's theme colours go in through globals())
                known |= set(vars(importlib.import_module(mod)))
                missing = sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
                                  and isinstance(n.ctx, ast.Load) and n.id not in known})
                self.assertEqual(missing, [], f"{mod}.py reads names that are never defined or imported")


if __name__ == "__main__":
    unittest.main()
