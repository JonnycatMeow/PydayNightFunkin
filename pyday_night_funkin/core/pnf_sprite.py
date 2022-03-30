
from math import pi, sin
import typing as t

from pyglet import gl
from pyglet.image import AbstractImage, TextureArrayRegion
from pyglet.math import Vec2
from pyday_night_funkin.core.animation.frames import AnimationFrame, FrameCollection

from pyday_night_funkin.core.constants import ERROR_TEXTURE
from pyday_night_funkin.core.graphics import PNFGroup
import pyday_night_funkin.core.graphics.state as s
from pyday_night_funkin.core.animation import Animation, AnimationController
from pyday_night_funkin.core.scene_context import SceneContext
from pyday_night_funkin.core.scene_object import WorldObject
from pyday_night_funkin.core.shaders import ShaderContainer
from pyday_night_funkin.core.tweens import TWEEN_ATTR
from pyday_night_funkin.core.utils import clamp

if t.TYPE_CHECKING:
	from pyglet.graphics.shader import UniformBufferObject
	from pyday_night_funkin.core.camera import Camera
	from pyday_night_funkin.core.types import Numeric

EffectBound = t.TypeVar("EffectBound", bound="Effect")


_PNF_SPRITE_VERTEX_SHADER_SOURCE = """
#version 450

in vec2 frame_offset;
in vec2 offset;
in vec2 origin;
in vec2 translate;
in vec4 colors;
in vec3 tex_coords;
in vec2 scale;
in vec2 position;
in vec2 scroll_factor;
in float rotation;

out vec4 vertex_colors;
out vec3 texture_coords;

uniform WindowBlock {{
	mat4 projection;
	mat4 view;
}} window;

layout(std140) uniform CameraAttrs {{
	float zoom;
	vec2  position;
	vec2  GAME_DIMENSIONS;
}} camera;


mat4 m_scale = mat4(1.0);
mat4 m_rotate = mat4(1.0);
mat4 m_translate = mat4(1.0);
mat4 m_camera_trans_scale = mat4(1.0);


void main() {{
	mat4 res_mat = mat4(1.0);
	mat4 work_mat = mat4(1.0);

	work_mat[3].xy = (
		origin +
		translate -
		(
			(camera.position * camera.zoom * scroll_factor) -
			offset
		)
	);
	res_mat *= work_mat; work_mat = mat4(1.0);

	work_mat[0][0] =  cos(-radians(rotation));
	work_mat[0][1] =  sin(-radians(rotation));
	work_mat[1][0] = -sin(-radians(rotation));
	work_mat[1][1] =  cos(-radians(rotation));
	res_mat *= work_mat; work_mat = mat4(1.0);

	work_mat[0][0] = scale.x;
	work_mat[1][1] = scale.y;
	res_mat *= work_mat; work_mat = mat4(1.0);

	work_mat[3].xy = frame_offset - origin;
	res_mat *= work_mat; work_mat = mat4(1.0);

	// Camera transform and zoom scale
	m_camera_trans_scale[3].xy = (
		(camera.zoom * -camera.GAME_DIMENSIONS / 2) +
		(camera.zoom * scroll_factor * -camera.position) +
		(camera.GAME_DIMENSIONS / 2)
	);
	m_camera_trans_scale[0][0] = camera.zoom;
	m_camera_trans_scale[1][1] = camera.zoom;

	// Notes for my dumbass cause simple things like matrices will never get into my head:
	// - Matrix multiplication is associative: A*(B*C) == (A*B)*C
	// - Matrix multiplication is not commutative: A*B != B*A
	// The last matrix in a multiplication chain will be the first operation.
	// So, to scale, rotate and THEN translate something (usual sane order):
	// `gl_Position = m_trans * m_rot * m_scale * vec4(position, 0, 1);`
	// Makes sense, really.

	gl_Position =
		window.projection *
		window.view *
		m_camera_trans_scale *
		res_mat *
		vec4(position, 0, 1)
	;

	vertex_colors = colors;
	texture_coords = tex_coords;
}}
"""

_PNF_SPRITE_FRAGMENT_SHADER_SOURCE = """
#version 450

in vec4 vertex_colors;
in vec3 texture_coords;

out vec4 final_color;

uniform sampler2D sprite_texture;

void main() {{
	final_color = {color_behavior};
}}
"""

class PNFSpriteVertexShader():
	src = _PNF_SPRITE_VERTEX_SHADER_SOURCE

	@classmethod
	def generate(cls) -> str:
		return cls.src.format()


class PNFSpriteFragmentShader():
	src = _PNF_SPRITE_FRAGMENT_SHADER_SOURCE

	class COLOR:
		BLEND = "texture(sprite_texture, texture_coords.xy) * vertex_colors"
		SET =   "vec4(vertex_colors.rgb, texture(sprite_texture, texture_coords.xy).a)"

	@classmethod
	def generate(cls, color_behavior: str = COLOR.BLEND) -> str:
		return cls.src.format(color_behavior=color_behavior)


class Movement():
	__slots__ = ("velocity", "acceleration")
	
	def __init__(self, velocity: Vec2, acceleration: Vec2) -> None:
		self.velocity = velocity
		self.acceleration = acceleration

	# Dumbed down case of code shamelessly stolen from https://github.com/HaxeFlixel/
	# flixel/blob/e3c3b30f2f4dfb0486c4b8308d13f5a816d6e5ec/flixel/FlxObject.hx#L738
	def update(self, dt: float) -> Vec2:
		acc_x, acc_y = self.acceleration
		vel_x, vel_y = self.velocity

		vel_delta = 0.5 * acc_x * dt
		vel_x += vel_delta
		posx_delta = vel_x * dt
		vel_x += vel_delta

		vel_delta = 0.5 * acc_y * dt
		vel_y += vel_delta
		posy_delta = vel_y * dt
		vel_y += vel_delta

		self.velocity = Vec2(vel_x, vel_y)

		return Vec2(posx_delta, posy_delta)


class Effect():
	"""
	"Abstract" effect class intertwined with the PNFSprite.
	"""
	def __init__(
		self,
		duration: float,
		on_complete: t.Optional[t.Callable[[], t.Any]] = None,
	) -> None:
		if duration <= 0.0:
			raise ValueError("Duration may not be negative or zero!")

		self.on_complete = on_complete
		self.duration = duration
		self.cur_time = 0.0

	def update(self, dt: float, sprite: "PNFSprite") -> None:
		raise NotImplementedError("Subclass this")

	def is_finished(self) -> bool:
		return self.cur_time >= self.duration


class _Tween(Effect):
	def __init__(
		self,
		tween_func: t.Callable[[float], float],
		attr_map: t.Dict[str, t.Tuple[t.Any, t.Any]],
		duration: float,
		on_complete: t.Optional[t.Callable[[], t.Any]] = None,
	) -> None:
		super().__init__(duration, on_complete)
		self.tween_func = tween_func
		self.attr_map = attr_map

	def update(self, dt: float, sprite: "PNFSprite") -> None:
		self.cur_time += dt
		progress = self.tween_func(clamp(self.cur_time, 0, self.duration) / self.duration)

		for attr_name, (v_ini, v_diff) in self.attr_map.items():
			setattr(sprite, attr_name, v_ini + v_diff*progress)


# NOTE: Left here since i would need to replace call sites with some
# ugly lambda s: setattr(s, "visibility", True) stuff; not really
# worth it, see into it if you have time.
class Flicker(Effect):
	"""
	Effect rapidly turning a sprite's visibility off and on.
	This is a special case of the more generic `Toggle` effect
	affecting only a sprite's visibility.
	"""
	def __init__(
		self,
		interval: float,
		start_visibility: bool,
		end_visibility: bool,
		duration: float,
		on_complete: t.Optional[t.Callable[[], t.Any]] = None,
	) -> None:
		super().__init__(duration, on_complete)
		if interval <= 0.0:
			raise ValueError("Interval may not be negative or zero!")

		self.interval = interval
		self.end_visibility = end_visibility
		self._next_toggle = interval
		self._visible = start_visibility

	def update(self, dt: float, sprite: "PNFSprite") -> None:
		self.cur_time += dt
		if self.is_finished():
			sprite.visible = self.end_visibility
			return

		if self.cur_time >= self._next_toggle:
			while self.cur_time >= self._next_toggle:
				self._next_toggle += self.interval
			self._visible = not self._visible
			sprite.visible = self._visible


class Toggle(Effect):
	"""
	Periodically calls on/off callbacks on a sprite for a given
	duration.
	"""
	def __init__(
		self,
		interval: float,
		start_active: bool,
		end_active: bool,
		duration: float,
		on_toggle_on: t.Optional[t.Callable[["PNFSprite"], t.Any]] = None,
		on_toggle_off: t.Optional[t.Callable[["PNFSprite"], t.Any]] = None,
		on_complete: t.Optional[t.Callable[[], t.Any]] = None,
	) -> None:
		super().__init__(duration, on_complete)
		if interval <= 0.0:
			raise ValueError("Interval may not be negative or zero!")

		self._cur_state = start_active
		self._invert = -1 if not start_active else 1
		self.interval = pi/interval
		self.end_active = end_active
		self.on_toggle_on = on_toggle_on
		self.on_toggle_off = on_toggle_off

	def update(self, dt: float, sprite: "PNFSprite") -> None:
		self.cur_time += dt
		new_state = (sin(self.cur_time * self.interval) * self._invert) > 0
		if self._cur_state == new_state:
			return

		self._cur_state = new_state
		if new_state:
			if self.on_toggle_on is not None:
				self.on_toggle_on(sprite)
		else:
			if self.on_toggle_off is not None:
				self.on_toggle_off(sprite)


class PNFSprite(WorldObject):
	"""
	Pretty much *the* core scene object, the sprite!
	It can show images or animations, do all sort of transforms, have
	a shader as well as cameras on it and comes with effect support.
	"""

	_TWEEN_ATTR_NAME_MAP = {
		TWEEN_ATTR.X: "x",
		TWEEN_ATTR.Y: "y",
		TWEEN_ATTR.ROTATION: "rotation",
		TWEEN_ATTR.OPACITY: "opacity",
		TWEEN_ATTR.SCALE: "scale",
		TWEEN_ATTR.SCALE_X: "scale_x",
		TWEEN_ATTR.SCALE_Y: "scale_y",
	}

	shader_container = ShaderContainer(
		PNFSpriteVertexShader.generate(),
		PNFSpriteFragmentShader.generate(),
	)

	def __init__(
		self,
		image: t.Optional[AbstractImage] = None,
		x: "Numeric" = 0,
		y: "Numeric" = 0,
		blend_src = gl.GL_SRC_ALPHA,
		blend_dest = gl.GL_ONE_MINUS_SRC_ALPHA,
		context: SceneContext = None,
		usage: t.Literal["dynamic", "stream", "static"] = "dynamic",
		subpixel: bool = False,
	) -> None:
		super().__init__(x, y)

		image = ERROR_TEXTURE if image is None else image

		self.animation = AnimationController(self)

		# NOTE: Copypaste of this exists at PNFSpriteContainer.__init__,
		# modify it when modifying this!
		self.movement: t.Optional[Movement] = None
		self.effects: t.List["EffectBound"] = []
		self._origin = (0, 0)
		self._offset = (0, 0)
		self.lazy_width: "Numeric" = 0
		self.lazy_height: "Numeric" = 0

		self._interfacer = None
		self._color = (255, 255, 255)
		self._opacity = 255

		self._frame: t.Optional[AnimationFrame] = None

		self._texture = image.get_texture()
		"""The currently displayed pyglet texture."""

		self._frames: t.Optional[FrameCollection] = None
		"""Frame collection frames and textures are drawn from."""

		if isinstance(image, TextureArrayRegion):
			raise NotImplementedError("Hey VSauce, Michael here. What is a TextureArrayRegion?")
			# program = sprite.get_default_array_shader()

		self._usage = usage
		self._subpixel = subpixel
		self._blend_src = blend_src
		self._blend_dest = blend_dest

		self._context = SceneContext() if context is None else context.inherit()

		self._create_interfacer()

		self.image = image

	def _build_gl_state(self, cam_ubo: "UniformBufferObject") -> s.GLState:
		return s.GLState.from_state_parts(
			s.ProgramStatePart(self.shader_container.get_program()),
			s.UBOBindingStatePart(cam_ubo),
			s.TextureUnitStatePart(gl.GL_TEXTURE0),
			s.TextureStatePart(self._texture),
			s.UniformStatePart("sprite_texture", 0),
			s.EnableStatePart(gl.GL_BLEND),
			s.SeparateBlendFuncStatePart(
				self._blend_src, self._blend_dest, gl.GL_ONE, self._blend_dest
			)
		)

	def _create_interfacer(self):
		#  0- - - - -3
		#  |\D>      ^
		#  A    \    E
		#  v      <C\|
		#  1----B>---2
		usage = self._usage
		self._interfacer = self._context.batch.add_indexed(
			4,
			gl.GL_TRIANGLES,
			self._context.group,
			(0, 1, 2, 0, 2, 3),
			{camera: self._build_gl_state(camera.ubo) for camera in self._context.cameras},
			"position2f/" + usage,
			("offset2f/" + usage, self._offset * 4),
			("origin2f/" + usage, self._origin * 4),
			("frame_offset2f/" + usage, (0, 0) * 4),
			("colors4Bn/" + usage, (*self._color, int(self._opacity)) * 4),
			("translate2f/" + usage, (self._x, self._y) * 4),
			("scale2f/" + usage, (self._scale * self._scale_x, self._scale * self._scale_y) * 4),
			("rotation1f/" + usage, (self._rotation,) * 4),
			("scroll_factor2f/" + usage, self._scroll_factor * 4),
			("tex_coords3f/" + usage, self._texture.tex_coords),
		)
		self._update_vertex_positions()

	def set_context(self, parent_context: SceneContext) -> None:
		"""
		This function actually doesn't set a context, it just
		modifies the existing one and takes all necessary steps for
		the sprite to be displayed in the new context.
		"""
		new_batch = parent_context.batch
		new_group = parent_context.group
		new_cams = parent_context.cameras
		old_batch = self._context.batch
		old_group = self._context.group
		old_cams = self._context.cameras

		change_batch = new_batch != old_batch
		rebuild_group = new_cams != old_cams or new_group != old_group.parent

		new_states = None
		if change_batch:
			self._context.batch = new_batch
			new_states = {cam: self._build_gl_state(cam.ubo) for cam in new_cams}

		if rebuild_group:
			self._context.cameras = new_cams
			self._context.group = PNFGroup(new_group)

		if change_batch or rebuild_group:
			self._interfacer.migrate(self._context.batch, self._context.group, new_states)

	def start_tween(
		self,
		tween_func: t.Callable[[float], float],
		attributes: t.Dict[TWEEN_ATTR, t.Any],
		duration: float,
		on_complete: t.Callable[[], t.Any] = None,
	) -> _Tween:
		"""
		# TODO write some very cool doc
		"""
		# 0: initial value; 1: difference
		attr_map = {}
		for attribute, target_value in attributes.items():
			attribute_name = self._TWEEN_ATTR_NAME_MAP[attribute]
			initial_value = getattr(self, attribute_name)
			attr_map[attribute_name] = (initial_value, target_value - initial_value)

		t = _Tween(
			tween_func,
			duration = duration,
			attr_map = attr_map,
			on_complete = on_complete,
		)
		self.effects.append(t)
		return t

	def start_flicker(
		self,
		duration: float,
		interval: float,
		end_visibility: bool = True,
		on_complete: t.Callable[[], t.Any] = None,
	) -> Flicker:
		f = Flicker(
			interval = interval,
			start_visibility = self.visible,
			end_visibility = end_visibility,
			duration = duration,
			on_complete = on_complete,
		)
		self.effects.append(f)
		return f

	def start_toggle(
		self,
		duration: float,
		interval: float,
		start_status: bool = True,
		end_status: bool = True,
		on_toggle_on: t.Optional[t.Callable[["PNFSprite"], t.Any]] = None,
		on_toggle_off: t.Optional[t.Callable[["PNFSprite"], t.Any]] = None,
		on_complete: t.Optional[t.Callable[[], t.Any]] = None,
	) -> Toggle:
		t = Toggle(
			interval, start_status, end_status, duration, on_toggle_on, on_toggle_off, on_complete
		)
		self.effects.append(t)
		return t

	def remove_effect(self, *effects: Effect) -> None:
		"""
		Removes effects from the sprite.
		Supply nothing to clear all effects. This will abruptly stop
		all effects without calling their on_complete callbacks.
		Supply any amount of effects to have only these removed.
		No exception is raised for non-existent effects.
		"""
		if not effects:
			self.effects.clear()
			return

		for e in effects:
			try:
				self.effects.remove(e)
			except ValueError:
				pass

	def start_movement(
		self,
		velocity: t.Union[Vec2, t.Tuple[float, float]],
		acceleration: t.Optional[t.Union[Vec2, t.Tuple[float, float]]] = None,
	) -> None:
		if not isinstance(velocity, Vec2):
			velocity = Vec2(*velocity)

		if acceleration is None:
			acceleration = Vec2(0, 0)
		elif not isinstance(acceleration, Vec2):
			acceleration = Vec2(*acceleration)

		self.movement = Movement(velocity, acceleration)

	def stop_movement(self) -> None:
		self.movement = None

	def center_offset(self) -> None:
		self.offset = (
			-0.5 * (self.width - self.lazy_width),
			-0.5 * (self.height - self.lazy_height),
		)

	def center_origin(self) -> None:
		self.origin = (
			0.5 * self._frame.source_dimensions[0],
			0.5 * self._frame.source_dimensions[1],
		)

	def refresh_offsets(self) -> None:
		self.lazy_width, self.lazy_height = self.width, self.height
		self.center_offset()
		self.center_origin()

	def check_animation_controller(self):
		"""
		Asks animation controller for a new frame and applies it.
		Useful for when waiting for `update` isn't possible during
		setup which i.e. depends on the first frame of an animation.
		"""
		if (new_offset := self.animation.query_new_animation_offset()) is not None:
			self.offset = (-new_offset[0], -new_offset[1])

		if (new_frame_idx := self.animation.query_new_frame()) is not None:
			self._set_frame(self._frames[new_frame_idx])

	def update(self, dt: float) -> None:
		if self.animation.is_set:
			self.animation.update(dt)
			self.check_animation_controller()

		if self.movement is not None:
			dx, dy = self.movement.update(dt)
			self.position = (self._x + dx, self._y + dy)

		if not self.effects:
			return

		finished_effects = []
		for effect in self.effects:
			effect.update(dt, self)
			if effect.is_finished():
				finished_effects.append(effect)

		for effect in finished_effects:
			if effect.on_complete is not None:
				effect.on_complete()
			try:
				self.effects.remove(effect)
			except ValueError:
				pass

	def _set_frame(self, frame: AnimationFrame):
		self._frame = frame
		texture = frame.texture
		prev_h, prev_w = self._texture.height, self._texture.width
		if texture.id is not self._texture.id:
			self._texture = texture
			self._interfacer.set_states(
				{camera: self._build_gl_state(camera.ubo) for camera in self._context.cameras}
			)
		else:
			self._texture = texture
		self._interfacer.set_data("tex_coords", texture.tex_coords)
		self._interfacer.set_data("frame_offset", tuple(frame.offset) * 4)
		# If this is not done, screws over vertices if the texture changes
		if prev_h != texture.height or prev_w != texture.width:
			self._update_vertex_positions()

	def _update_vertex_positions(self):
		img = self._texture
		x1 = -img.anchor_x
		y1 = -img.anchor_y + img.height
		x2 = -img.anchor_x + img.width
		y2 = -img.anchor_y

		if self._subpixel:
			self._interfacer.set_data("position", (x1, y1, x2, y1, x2, y2, x1, y2))
		else:
			self._interfacer.set_data(
				"position", tuple(map(int, (x1, y1, x2, y1, x2, y2, x1, y2)))
			)

	def delete(self):
		"""
		Deletes this sprite's graphical resources.
		"""
		self._interfacer.delete()
		self._interfacer = None
		self._texture = None
		self._context = None # GC speedup, probably
		self.animation = None

	@property
	def signed_width(self) -> float:
		return self._scale_x * self._scale * self._frame.source_dimensions[0]

	@property
	def signed_height(self) -> float:
		return self._scale_y * self._scale * self._frame.source_dimensions[1]

	# === Simple properties and private methods below === #

	@property
	def image(self) -> AbstractImage:
		"""
		The sprite's currently displayed image.
		May be from an animation if one is playing.
		"""
		return self._texture

	@image.setter
	def image(self, image: AbstractImage) -> None:
		fc = FrameCollection()
		fc.add_frame(image.get_texture(), Vec2(image.width, image.height), Vec2())
		self.frames = fc

	@property
	def frames(self) -> FrameCollection:
		return self._frames

	@frames.setter
	def frames(self, new_frames: FrameCollection) -> None:
		self.animation.delete_animations()
		self._frames = new_frames
		self._set_frame(new_frames.frames[0])
		self.lazy_width, self.lazy_height = self._frame.source_dimensions
		self.center_origin()

	@property
	def x(self) -> "Numeric":
		"""The sprite's x coordinate."""
		return self._x

	@x.setter
	def x(self, new_x: "Numeric") -> None:
		self._x = new_x
		self._interfacer.set_data("translate", (new_x, self._y) * 4)

	@property
	def y(self) -> "Numeric":
		"""The sprite's y coordinate."""
		return self._y

	@y.setter
	def y(self, new_y: "Numeric") -> None:
		self._y = new_y
		self._interfacer.set_data("translate", (self._x, new_y) * 4)

	@property
	def position(self) -> t.Tuple["Numeric", "Numeric"]:
		"""
		The sprite's position. Sets both x and y at the same time and
		should run just about 3.7% faster.
		"""
		return (self._x, self._y)

	@position.setter
	def position(self, new_position: t.Tuple["Numeric", "Numeric"]) -> None:
		self._x, self._y = new_position
		self._interfacer.set_data("translate", new_position * 4)

	@property
	def rotation(self) -> float:
		"""The sprite's rotation, in degrees."""
		return self._rotation

	@rotation.setter
	def rotation(self, new_rotation: float) -> None:
		self._rotation = new_rotation
		self._interfacer.set_data("rotation", (new_rotation,) * 4)

	@property
	def scale_x(self) -> "Numeric":
		"""
		The sprite's scale along the x axis.
		"""
		return self._scale_x

	@scale_x.setter
	def scale_x(self, new_scale_x: "Numeric") -> None:
		self._scale_x = new_scale_x
		self._interfacer.set_data(
			"scale", (self._scale * new_scale_x, self._scale * self._scale_y) * 4
		)

	@property
	def scale_y(self) -> "Numeric":
		"""
		The sprite's scale along the y axis.
		"""
		return self._scale_y

	@scale_y.setter
	def scale_y(self, new_scale_y: "Numeric") -> None:
		self._scale_y = new_scale_y
		self._interfacer.set_data(
			"scale", (self._scale * self._scale_x, self._scale * new_scale_y) * 4
		)

	@property
	def scale(self) -> "Numeric":
		"""
		The sprite's scale along both axes.
		"""
		return self._scale

	@scale.setter
	def scale(self, new_scale: "Numeric") -> None:
		self._scale = new_scale
		self._interfacer.set_data(
			"scale",
			(new_scale * self._scale_x, new_scale * self._scale_y) * 4,
		)

	@property
	def origin(self) -> t.Tuple["Numeric", "Numeric"]:
		"""
		The sprite's origin. TODO I can't tell what this does yet
		"""
		return self._origin

	@origin.setter
	def origin(self, new_origin: t.Tuple["Numeric", "Numeric"]) -> None:
		self._origin = new_origin
		self._interfacer.set_data("origin", new_origin * 4)

	@property
	def offset(self) -> t.Tuple["Numeric", "Numeric"]:
		"""
		Sprite offset.
		Going by Flixel, technically, this is supposed to only affect
		the hitbox, but it's flat-out used in rendering code, so that's
		a lie.
		# TODO check and figure out doc
		Also, in FnF's source, this value is misused. offset is set
		when frame data is set, depending on the first fucking frame in
		a sprite sheet. this has then influenced manually set
		per-animation offsets, that will likely break completely if
		`updateHitbox` should ever be called. I can tell this is going
		to be a pain to figure out and rectify.
		"""
		return self._offset

	@offset.setter
	def offset(self, new_offset: t.Tuple["Numeric", "Numeric"]) -> None:
		self._offset = new_offset
		self._interfacer.set_data("offset", new_offset * 4)

	@property
	def scroll_factor(self) -> t.Tuple[float, float]:
		"""
		The sprite's scroll factor.
		Determines how hard camera movement will displace the sprite.
		Very useful for parallax effects.
		"""
		return self._scroll_factor

	@scroll_factor.setter
	def scroll_factor(self, new_sf: t.Tuple[float, float]) -> None:
		self._scroll_factor = new_sf
		self._interfacer.set_data("scroll_factor", new_sf * 4)

	@property
	def color(self) -> t.Tuple[int, int, int]:
		"""
		The sprite's color tint.
		This may have wildly varying results if a special shader
		was set.
		"""
		return self._color

	@color.setter
	def color(self, new_color: t.Tuple[int, int, int]) -> None:
		self._color = new_color
		self._interfacer.set_data("colors", (*new_color, self._opacity) * 4)

	@property
	def opacity(self) -> int:
		"""
		The sprite's opacity.
		0 is completely transparent, 255 completely opaque.
		"""
		return self._opacity

	@opacity.setter
	def opacity(self, new_opacity: "Numeric") -> None:
		new_opacity = int(new_opacity)
		self._opacity = new_opacity
		self._interfacer.set_data("colors", (*self._color, new_opacity) * 4)

	@property
	def visible(self) -> bool:
		"""
		Whether the sprite should be drawn.
		"""
		return self._interfacer._visible

	@visible.setter
	def visible(self, visible: bool) -> None:
		self._interfacer.set_visibility(visible)
