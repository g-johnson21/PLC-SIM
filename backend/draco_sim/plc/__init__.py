"""LD / ST / SFC engine for the Draco training simulator.

Lifecycle: compile_program(...) -> PlcRuntime(tags, programs) -> write_inputs ->
scan(dt) -> read_outputs. See docs/plc-language.md for the languages and the
document schemas.
"""

from .errors import CompileError, PlcFault, PlcStateError
from .fb import FB_TYPES
from .funcs import FUNCTION_NAMES
from .ladder import LD_VERSION, ladder_to_text
from .program import CompiledProgram, compile_file, compile_program
from .runtime import PlcRuntime, ScanResult
from .sfc import SFC_VERSION
from .tagspecs import DRACO_TAGSPECS_PLACEHOLDER
from .types import TagSpec

__all__ = [
    "CompileError",
    "CompiledProgram",
    "DRACO_TAGSPECS_PLACEHOLDER",
    "FB_TYPES",
    "FUNCTION_NAMES",
    "LD_VERSION",
    "PlcFault",
    "PlcRuntime",
    "PlcStateError",
    "SFC_VERSION",
    "ScanResult",
    "TagSpec",
    "compile_file",
    "compile_program",
    "ladder_to_text",
]
