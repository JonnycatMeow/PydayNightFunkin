
# Generates an include file for vertexbuffer.pyx
# If i didn't forget to update the comment, this file is expected to deliver:
#
# - The function type `FPTR_pyobj_extractor`. (size_t s, void *t, PyObject *o) -> uint8_t
# - A function `get_pyobj_extractor_function` that takes any of the
#   PNF_OPEN_GL_TYPE_DEFINITIONS types and delivers a pointer to a function of the above type.
#   The functions must take [s?] elements from o and populate the region t points to with
#   equivalent C types.
# - Verification functions:
#    - _verify_index_access(size_t bufsize, size_t i)
#    - _verify_range_access(size_t bufsize, size_t s, size_t l)
#    - _verify_is_ctypes_array(PyObject *o)
#   These must raise either exceptions when the arguments don't work out or do nothing
#   for the HYPER_UNSAFE flag.
#   They also should be `inline`.

from pathlib import Path
import sys
import textwrap

HYPER_UNSAFE = "--hyper-unsafe" in sys.argv

#########################################################################################
# ! Check the entire codebase for "PNF_OPEN_GL_TYPE_DEFINITIONS" when modifiying this ! #
#########################################################################################
TYPES = (
	("GL_BYTE",           "byte",           1, "int8_t",   ("int",)),
	("GL_UNSIGNED_BYTE",  "unsigned_byte",  1, "uint8_t",  ("int",)),
	("GL_SHORT",          "short",          2, "int16_t",  ("int",)),
	("GL_UNSIGNED_SHORT", "unsigned_short", 2, "uint16_t", ("int",)),
	("GL_INT",            "int",            4, "int32_t",  ("int",)),
	("GL_UNSIGNED_INT",   "unsigned_int",   4, "uint32_t", ("int",)),
	("GL_FLOAT",          "float",          4, "float",    ("int", "float")),
	("GL_DOUBLE",         "double",         8, "double",   ("int", "float")),
)

HEADER = """
#                           NOTICE                           #
# This file was autogenerated by `vertexbuffer_gen.py`.      #
# Do not modify it! (Or do, i'm not your dad.)               #
# For permanent changes though, modify the generator script. #

ctypedef uint8_t (* FPTR_pyobj_extractor)(size_t size, void *target, object data_collection) except 1
"""

EXTRACTOR_SKELETON_SAFETY_BLOCK = """
		if not isinstance(it, {expected_py_types}):
			raise TypeError(f"Bad python type {{type(it)!r}} for supplied buffer data.")
		if i >= size:
			break
"""

EXTRACTOR_SKELETON = """
cdef uint8_t extract_{{c_type_name}}s(size_t size, void *target, object data_collection) except 1:
	cdef {{c_typedef}} *cast_target = <{{c_typedef}} *>target
	cdef size_t i = 0
	for i, it in enumerate(data_collection):{}
		cast_target[i] = <{{c_typedef}}>it
	return 0
""".format("" if HYPER_UNSAFE else EXTRACTOR_SKELETON_SAFETY_BLOCK)


GET_EXTRACTOR_TEMPLATE = """
cdef inline FPTR_pyobj_extractor get_pyobj_extractor_function(GLenum gl_type):
{}
	return NULL
"""

VERIFIER_SIG_HEAD = "@cython.unraisable_tracebacks(True)\ncdef inline uint8_t "
VERIFIER_SIG_TAIL = " except 1:"
VERIFIERS = (
	(
		"_verify_index_access(size_t buf_size, size_t index)",
		"""
		if index >= buf_size:
			raise IndexError(f"Index {index} out of bounds for buffer of size {buf_size}.")
		return 0
		"""
	),
	(
		"_verify_range_access(size_t buf_size, size_t start, size_t range_size)",
		"""
		# Some functions (e.g. memmove) state their arguments must be valid pointers,
		# whether the size of the copied region is 0 is irrelevant.
		# Also, in theory, if such an insanely large start and range size were passed that
		# they overflowed they could cause the start access to fail and the other to succeed.
		_verify_index_access(buf_size, start)
		if range_size > 0:
			_verify_index_access(buf_size, start + range_size - 1)
		return 0
		"""
	),
	(
		"_verify_is_ctypes_array(object o)",
		"""
		if not isinstance(o, ctypes_Array):
			raise TypeError("Object must be a ctypes array!")
		return 0
		"""
	),
)


def main():
	_path = Path("PydayNightFunkin/pyday_night_funkin/core/graphics")
	generator_path = Path.cwd()
	while _path.parts:
		head, *tail = _path.parts
		if generator_path.name == head:
			generator_path /= Path(*tail)
			break
		_path = Path(*tail)
	else:
		return 1

	funcdefs = []

	# === Extractor definitions === #

	for _, func_name, size, c_typedef, python_types in TYPES:
		isinstance_arg = (
			python_types[0] if len(python_types) == 1
			else '(' + ', '.join(python_types) + ')'
		)
		func = EXTRACTOR_SKELETON.format(
			c_type_name = func_name,
			c_typedef = c_typedef,
			expected_py_types = isinstance_arg,
			cast_safety = '' if HYPER_UNSAFE else '?',
		)
		funcdefs.append(func)

	# === Extractor getter function === #

	extractor_switch = ""
	for i, (gl_type_name, c_name, _, _, _) in enumerate(TYPES):
		word = "if" if i == 0 else "elif"
		extractor_switch += f"\t{word} gl_type == {gl_type_name}:\n"
		extractor_switch += f"\t\treturn extract_{c_name}s\n"

	extractor_getter = GET_EXTRACTOR_TEMPLATE.format(extractor_switch)

	# === Verifiers === #

	verifiers = ""
	for sig_stub, body in VERIFIERS:
		verifiers += VERIFIER_SIG_HEAD + sig_stub + VERIFIER_SIG_TAIL
		body = (
			"\n\treturn 0\n" if HYPER_UNSAFE
			else textwrap.indent(textwrap.dedent(body), '\t')
		)
		verifiers += (body + '\n')

	with (generator_path / "vertexbuffer.pxi").open("w", encoding="utf-8") as f:
		f.write(HEADER + "".join(funcdefs) + extractor_getter + '\n' + verifiers)

if __name__ == "__main__":
	sys.exit(main())
