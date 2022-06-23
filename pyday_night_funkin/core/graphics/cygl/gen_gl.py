
from pathlib import Path
import sys

from opengl_registry import RegistryReader


# OpenGL function addresses must be resolved at runtime. Usually, something like GLAD does this.
# Luckily, this is awesome pyglet-land, so we are able to piggyback off of pyglet's loading
# routines to get all these sweet function pointers down to cython.
# This script autogenerates a cython module that does exactly that. Pass it pyglet's gl module
# and it will populate a C struct that serves as the central registry.
# Other cython modules that want to interact with OpenGL can then cimport `cygl_get_reg` and use
# that registry.


PXD_TEMPLATE = """
from libc.stdint cimport *


ctypedef unsigned int GLenum
ctypedef unsigned char GLboolean
ctypedef void GLvoid
ctypedef int GLint
ctypedef unsigned int GLuint
ctypedef int GLsizei
ctypedef unsigned long int GLsizeiptr
ctypedef long int GLintptr
ctypedef double GLdouble
ctypedef char GLchar
ctypedef unsigned int GLbitfield

{funcptr_defs}

cdef extern from *:
	\"\"\"
{gl_constant_c_defines}	\"\"\"
{gl_constant_cython_extern_defs}

ctypedef struct GLRegistry:
{gl_registry_struct_def}

cdef GLRegistry *cygl_get_reg() except NULL
cdef uint8_t cygl_errcheck() except 1
cdef size_t cygl_get_gl_type_size(GLenum type_)
"""


PYX_TEMPLATE = """
import ctypes
from pyday_night_funkin.core.graphics.cygl cimport gl

cdef bint _is_initialized = False

cdef gl.GLRegistry _gl_reg

ctypedef void (* SetGLFunc_f)(size_t addressof)

# Completely unsafe hacks that make function addresses available to cython.
# I love and hate C for this.
# https://stackoverflow.com/questions/49635105/ctypes-get-the-actual-address-of-a-c-function

{initializer_funcs}

class OpenGLError(Exception):
	pass


cdef GLRegistry *cygl_get_reg() except NULL:
	if not _is_initialized:
		raise RuntimeError("cygl was not initialized!")
	return &_gl_reg

cdef uint8_t cygl_errcheck() except 1:
	if not _is_initialized:
		raise RuntimeError("cygl was not initialized!")

	cdef GLenum err = _gl_reg.GetError()
	if err == 0:
		return 0

	cdef str err_str = "Unkown error code. Something is seriously off."
	if err == GL_INVALID_ENUM:
		err_str = "Invalid enum value (Oooh what could the cause for this one be?)"
	elif err == GL_INVALID_VALUE:
		err_str = "Invalid value (Most descriptive OpenGL error)"
	elif err == GL_INVALID_OPERATION:
		err_str = "Invalid operation (Happy guessing!)"
	elif err == GL_INVALID_FRAMEBUFFER_OPERATION:
		err_str = "Invalid Framebuffer operation"
	elif err == GL_OUT_OF_MEMORY:
		err_str = "Out of memory"
	raise OpenGLError(err_str)

#########################################################################################
# ! Check the entire codebase for "PNF_OPEN_GL_TYPE_DEFINITIONS" when modifiying this ! #
#########################################################################################
cdef size_t cygl_get_gl_type_size(GLenum type_):
	if type_ in (GL_BYTE, GL_UNSIGNED_BYTE):
		return 1
	elif type_ in (GL_SHORT, GL_UNSIGNED_SHORT):
		return 2
	elif type_ in (GL_INT, GL_UNSIGNED_INT, GL_FLOAT):
		return 4
	elif type_ in (GL_DOUBLE,):
		return 8
	else:
		return 0


NEEDS_INITIALIZATION = {command_translation_dict}

def initialize(module):
	global _is_initialized
	if _is_initialized:
		return

	cdef set uninitialized = set(NEEDS_INITIALIZATION)
	for name in dir(module):
		if name in NEEDS_INITIALIZATION:
			# print("initing", name)
			f = NEEDS_INITIALIZATION[name]
			f(<size_t>ctypes.addressof(getattr(module, name)))
			uninitialized.remove(name)

	if uninitialized:
		raise RuntimeError(
			f"The cython GL registry was not fully initialized."
			f"First missing value: {{next(iter(uninitialized))!r}}"
		)

	# print("in'nit")
	_is_initialized = True
"""


DEFINED_TYPES = {
	"GLenum", "GLboolean", "GLvoid", "GLint", "GLuint", "GLsizei",
	"GLsizeiptr", "GLintptr", "GLdouble", "GLchar", "GLbitfield"
}

REQUIRED_ENUMS = {
	"GL_DYNAMIC_READ",
	"GL_READ_ONLY",
	"GL_MAP_READ_BIT",

	"GL_INVALID_ENUM",
	"GL_INVALID_VALUE",
	"GL_INVALID_OPERATION",
	"GL_INVALID_FRAMEBUFFER_OPERATION",
	"GL_OUT_OF_MEMORY",

	# ! These should always be the same set of   ! #
	# ! type names found in core.graphics.shared ! #
	"GL_BYTE",
	"GL_UNSIGNED_BYTE",
	"GL_SHORT",
	"GL_UNSIGNED_SHORT",
	"GL_INT",
	"GL_UNSIGNED_INT",
	"GL_FLOAT",
	"GL_DOUBLE",
}

REQUIRED_COMMANDS = {
	"glGetError": "GetError",

	# Buffer stuff
	"glCreateBuffers": "CreateBuffers",
	"glDeleteBuffers": "DeleteBuffers",

	"glBufferData": "BufferData",
	"glNamedBufferData": "NamedBufferData",
	"glBufferSubData": "BufferSubData",
	"glNamedBufferSubData": "NamedBufferSubData",

	"glMapNamedBuffer": "MapNamedBuffer",
	"glMapNamedBufferRange": "MapNamedBufferRange",
	"glUnmapNamedBuffer": "UnmapNamedBuffer",

	"glBindBuffer": "BindBuffer",
}

def _make_funcptr_name(name: str) -> str:
	return "FPTR_" + name


def main():
	_path = Path("PydayNightFunkin/pyday_night_funkin/core/graphics/cygl")
	cygl_path = Path.cwd()
	while _path.parts:
		head, *tail = _path.parts
		if cygl_path.name == head:
			cygl_path /= Path(*tail)
			break
		_path = Path(*tail)
	else:
		print("Could not correct cwd to cygl subdirectory.")
		return 1

	gl_reg_struct_members = ""

	rr = RegistryReader.from_url()
	# rr = RegistryReader.from_file("/tmp/gl.xml")

	enum_defines = ""
	enum_cython_externs = ""
	funcptr_defs = ""
	# Add needed enums
	for enum in rr.read_enums().values():
		if enum.name in REQUIRED_ENUMS:
			enum_defines += f"\t#define {enum.name} {enum.value}\n"
			enum_cython_externs += f"\tGLenum {enum.name}\n"

	# Add needed command declarations
	for name, cmd in rr.read_commands().items():
		if name not in REQUIRED_COMMANDS:
			continue

		args = []
		for prm in cmd.params:
			if "void" in prm.value:
				args.append("const void *" + prm.name)
			elif prm.ptype is None:
				print(f"missing param type for {prm.name} of {cmd.name}.")
				return 1
			else:
				if prm.ptype not in DEFINED_TYPES:
					print(f"type {prm.ptype!r} is not defined")
					return 1
				args.append(prm.value)

		rtype = "void " + ('*' * cmd.proto.count('*'))
		if cmd.ptype is not None:
			rtype = cmd.ptype
			if rtype not in DEFINED_TYPES:
				print(f"type {rtype!r} is not defined")
				return 1
			rtype += ' '

		translated_name = REQUIRED_COMMANDS[name]
		fptr_name = _make_funcptr_name(translated_name)
		funcptr_defs += f"ctypedef {rtype}(* {fptr_name})({', '.join(args)})\n"
		gl_reg_struct_members += f"\t{fptr_name} {translated_name}\n"


	command_translation_dict = "{\n"
	initializer_funcs = ""
	for orig_name, cy_name in REQUIRED_COMMANDS.items():
		fptr_name = _make_funcptr_name(cy_name)
		regfunc_name = f"_register_{orig_name}"
		initializer_funcs += f"cdef void {regfunc_name}(size_t func_ptr):\n"
		initializer_funcs += f"\t_gl_reg.{cy_name} = (<{fptr_name} *>func_ptr)[0]\n\n"
		command_translation_dict += f"\t\"{orig_name}\": {regfunc_name},\n"

	command_translation_dict += "}\n"

	with (cygl_path / "gl.pxd").open("w", encoding="utf-8") as f:
		f.write(PXD_TEMPLATE.format(
			funcptr_defs = funcptr_defs,
			gl_constant_c_defines = enum_defines,
			gl_constant_cython_extern_defs = enum_cython_externs,
			gl_registry_struct_def = gl_reg_struct_members,
		))

	with (cygl_path / "gl.pyx").open("w", encoding="utf-8") as f:
		f.write(PYX_TEMPLATE.format(
			initializer_funcs = initializer_funcs,
			command_translation_dict = command_translation_dict,
		))

	return 0


if __name__ == "__main__":
	sys.exit(main())
