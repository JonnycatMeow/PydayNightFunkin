
import typing as t

from pyglet import gl
from pyglet import graphics
from pyglet.graphics.shader import ShaderProgram
from pyglet.image import AbstractImage, Texture, TextureArrayRegion
from pyglet.math import Vec2

import pyday_night_funkin.constants as CNST
from pyday_night_funkin.core.tweens import TWEEN_ATTR
from pyday_night_funkin.core.context import Context
from pyday_night_funkin.core.pnf_animation import AnimationController, PNFAnimation
from pyday_night_funkin.core.graphics import PNFGroup
import pyday_night_funkin.core.graphics.states as s
from pyday_night_funkin.core.scene_object import SceneObject
from pyday_night_funkin.core.shaders import ShaderContainer
from pyday_night_funkin.utils import clamp

if t.TYPE_CHECKING:
	from pyglet.graphics.shader import UniformBufferObject
	from pyday_night_funkin.core.camera import Camera
	from pyday_night_funkin.types import Numeric

EffectBound = t.TypeVar("EffectBound", bound="Effect")


_PNF_SPRITE_VERTEX_SHADER_SOURCE = """
#version 450

in vec2 anim_offset;
in vec2 frame_offset;
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

// Not really sure about having GAME_DIMENSIONS here
// since it's by all means a constant

layout (std140) uniform CameraAttrs {{
	float zoom;
	vec2  position;
	vec2  GAME_DIMENSIONS;
}} camera;


mat4 m_trans_scale = mat4(1.0);
mat4 m_rotation = mat4(1.0);
mat4 m_camera_trans_scale = mat4(1.0);
mat4 m_camera_pre_trans = mat4(1.0);


void main() {{
	m_trans_scale[3][0] = translate.x + anim_offset.x + frame_offset.x * scale.x;
	m_trans_scale[3][1] = translate.y + anim_offset.y + frame_offset.y * scale.y;
	m_trans_scale[0][0] = scale.x;
	m_trans_scale[1][1] = scale.y;
	m_rotation[0][0] =  cos(-radians(rotation));
	m_rotation[0][1] =  sin(-radians(rotation));
	m_rotation[1][0] = -sin(-radians(rotation));
	m_rotation[1][1] =  cos(-radians(rotation));
	// Camera transform and zoom scale
	m_camera_trans_scale[3][0] = (camera.zoom * scroll_factor.x * -camera.position.x) + \\
		(camera.GAME_DIMENSIONS.x / 2);
	m_camera_trans_scale[3][1] = (camera.zoom * scroll_factor.y * -camera.position.y) + \\
		(camera.GAME_DIMENSIONS.y / 2);
	m_camera_trans_scale[0][0] = camera.zoom;
	m_camera_trans_scale[1][1] = camera.zoom;
	// Camera pre-scale-transform
	m_camera_pre_trans[3][0] = -camera.GAME_DIMENSIONS.x / 2;
	m_camera_pre_trans[3][1] = -camera.GAME_DIMENSIONS.y / 2;

	gl_Position =
		window.projection *
		window.view *
		m_camera_trans_scale *
		m_camera_pre_trans *
		m_trans_scale *
		m_rotation *
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

out vec4 final_colors;

uniform sampler2D sprite_texture;


void main() {{
	if (vertex_colors.a < {alpha_limit}) {{
		discard;
	}}

	final_colors = {color_behavior};
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
	def generate(
		cls,
		alpha_limit: float = 0.01,
		color_behavior: str = COLOR.BLEND,
	) -> str:
		return cls.src.format(
			alpha_limit=alpha_limit,
			color_behavior=color_behavior,
		)


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


class Tween(Effect):
	def __init__(
		self,
		tween_func: t.Callable,
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
			setattr(sprite, attr_name, v_ini + v_diff * progress)


class Flicker(Effect):
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


class PNFSprite(SceneObject):
	"""
	Pretty much *the* core scene object, the sprite!
	It can show images or animations, do all sort of transforms, have
	a shader as well as a camera on it and comes with effect support.
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
	_dummy_camera = None

	def __init__(
		self,
		camera: t.Optional["Camera"] = None,
		image: t.Optional[AbstractImage] = None,
		x: "Numeric" = 0,
		y: "Numeric" = 0,
		blend_src = gl.GL_SRC_ALPHA,
		blend_dest = gl.GL_ONE_MINUS_SRC_ALPHA,
		context: Context = None,
		usage: t.Literal["dynamic", "stream", "static"] = "dynamic",
		subpixel: bool = False,
		program: "ShaderProgram" = None,
	) -> None:
		image = CNST.ERROR_TEXTURE if image is None else image

		self.animation = AnimationController()
		self.camera = self._get_dummy_camera() if camera is None else camera

		# NOTE: Copypaste of this exists at PNFSpriteContainer.__init__,
		# modify it when modifying this!
		self.movement: t.Optional[Movement] = None
		self.effects: t.List["EffectBound"] = []

		self._x = x
		self._y = y
		self._batch = None
		self._vertex_list = None
		self._rotation = 0
		self._opacity = 255
		self._rgb = (255, 255, 255)
		self._scale = 1.0
		self._scale_x = 1.0
		self._scale_y = 1.0
		self._scroll_factor = (1.0, 1.0)
		self._visible = True
		self._texture = eval("image.get_texture()") # stfu pylance

		if isinstance(image, TextureArrayRegion):
			raise NotImplementedError("Hey VSauce, Michael here. What is a TextureArrayRegion?")
			# program = sprite.get_default_array_shader()
		else:
			program = self.shader_container.get_program()

		self._usage = usage
		self._subpixel = subpixel
		self._blend_src = blend_src
		self._blend_dest = blend_dest

		self._context = Context(
			graphics.get_default_batch() if context is None else context.batch,
			PNFGroup(
				parent = None if context is None else context.group,
				states = self._build_mutators(program)
			)
		)

		self._create_vertex_list()

		self.image = image

	@classmethod
	def _get_dummy_camera(cls):
		if cls._dummy_camera is None:
			from pyday_night_funkin.core.camera import Camera
			cls._dummy_camera = Camera()
		return cls._dummy_camera

	def _build_mutators(self, program: "ShaderProgram"):
		return (
			s.ProgramStateMutator(program),
			s.UBOBindingStateMutator(self.camera.ubo),
			s.TextureUnitStateMutator(gl.GL_TEXTURE0),
			s.TextureStateMutator(self._texture),
			s.EnableStateMutator(gl.GL_BLEND),
			s.BlendFuncStateMutator(self._blend_src, self._blend_dest),
		)

	def _create_vertex_list(self):
		#  0- - - - -3
		#  |\D>      ^
		#  A    \    E
		#  v      <C\|
		#  1----B>---2
		usage = self._usage
		self._vertex_list = self._context.batch.add_indexed(
			4,
			gl.GL_TRIANGLES,
			self._context.group,
			[0, 1, 2, 0, 2, 3],
			"position2f/" + usage,
			("anim_offset2f/" + usage, (0, 0) * 4),
			("frame_offset2f/" + usage, (0, 0) * 4),
			("colors4Bn/" + usage, (*self._rgb, int(self._opacity)) * 4),
			("translate2f/" + usage, (self._x, self._y) * 4),
			("scale2f/" + usage, (self._scale * self._scale_x, self._scale * self._scale_y) * 4),
			("rotation1f/" + usage, (self._rotation, ) * 4),
			("scroll_factor2f/" + usage, self._scroll_factor * 4),
			("tex_coords3f/" + usage, self._texture.tex_coords),
		)
		self._update_position()

	def set_context(self, parent_context: "Context") -> None:
		new_batch = parent_context.batch
		new_group = parent_context.group
		old_batch = self._context.batch
		old_group = self._context.group

		# NOTE: migrate may be called twice here which is inefficient but unlikely since
		# why should batches ever be switched anyways
		if new_batch != old_batch:
			if new_batch is not None and old_batch is not None:
				old_batch.migrate(self._vertex_list, gl.GL_TRIANGLES, self._context.group, new_batch)
				self._context.batch = new_batch
			else:
				self._vertex_list.delete()
				self._context.batch = new_batch
				self._create_vertex_list()

		if new_group != old_group.parent:
			self._context.group = PNFGroup(
				parent = new_group,
				states = self._build_mutators(old_group.program)
			)
			self._context.batch.migrate(
				self._vertex_list, gl.GL_TRIANGLES, self._context.group, self._context.batch
			)

	def screen_center(self, screen_dims: Vec2, x: bool = True, y: bool = True) -> None:
		"""
		Sets the sprite's world position so that it is centered 
		on screen. (Ignoring camera and scroll factors)
		`x` and `y` can be set to false to only center the sprite
		along one of the axes.
		"""
		if x:
			self.x = (screen_dims[0] - self.width) // 2
		if y:
			self.y = (screen_dims[1] - self.height) // 2

	def get_midpoint(self) -> Vec2:
		"""
		Returns the middle point of this sprite, based on its current
		texture and world position.
		"""
		return Vec2(
			self._x + self.signed_width * 0.5,
			self._y + self.signed_height * 0.5,
		)

	def start_tween(
		self,
		tween_func: t.Callable[[float], float],
		attributes: t.Dict[TWEEN_ATTR, t.Any],
		duration: float,
		on_complete: t.Callable[[], t.Any] = None,
	) -> Tween:
		"""
		# TODO write some very cool doc
		"""
		# 0: initial value; 1: difference
		attr_map = {}
		for attribute, target_value in attributes.items():
			attribute_name = self._TWEEN_ATTR_NAME_MAP[attribute]
			initial_value = getattr(self, attribute_name)
			attr_map[attribute_name] = (initial_value, target_value - initial_value)

		t = Tween(
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

	def start_movement(
		self,
		velocity: t.Union[Vec2, t.Tuple[float, float]],
		acceleration: t.Optional[t.Union[Vec2, t.Tuple[float, float]]] = None,
	) -> None:
		if not isinstance(velocity, Vec2):
			velocity = Vec2(*velocity)

		if acceleration is not None and not isinstance(acceleration, Vec2):
			acceleration = Vec2(*acceleration)

		self.movement = Movement(velocity, acceleration)

	def stop_movement(self) -> None:
		self.movement = None

	def check_animation_controller(self):
		"""
		Tests animation controller for new textures or offsets
		and applies them to the sprite.
		Useful for when waiting for `update` isn't possible during
		setup which i.e. depends on the first frame of an animation.
		"""
		if (new_frame := self.animation.query_new_texture()) is not None:
			self._set_texture(new_frame)

		if (new_offset := self.animation.query_new_offset()) is not None:
			self._vertex_list.anim_offset[:] = new_offset * 4

		if (new_frame_offset := self.animation.query_new_frame_offset()) is not None:
			self._vertex_list.frame_offset[:] = new_frame_offset * 4

	def update(self, dt: float) -> None:
		if self.animation.is_set:
			self.animation.update(dt)
			self.check_animation_controller()

		if self.movement is not None:
			dx, dy = self.movement.update(dt)
			self.x += dx
			self.y += dy

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

	@property
	def width(self) -> float:
		return abs(self.signed_width)

	@property
	def height(self):
		return abs(self.signed_height)

	@property
	def signed_width(self) -> float:
		return self._scale_x * self._scale * (
			self.animation._base_box[0] if self.animation.is_set else
			self._texture.width
		)

	@property
	def signed_height(self) -> float:
		return self._scale_y * self._scale * (
			self.animation._base_box[1] if self.animation.is_set else
			self._texture.height
		)

	# === Copypasted methods from the standard pyglet sprite === #

	def delete(self):
		"""
		Deletes this sprite's vertex list immediatedly and removes
		its texture and group.
		"""
		self._vertex_list.delete()
		self._vertex_list = None
		self._texture = None
		self._context = None # GC speedup, probably

	def draw(self):
		"""
		Draws this sprite inefficiently.
		Batches should be used instead.
		"""
		self._context.group.set_state_recursive()
		self._vertex_list.draw(gl.GL_TRIANGLES)
		self._context.group.unset_state_recursive()

	# === Simple/Copypasted properties and private methods below === #

	@property
	def image(self) -> t.Union[PNFAnimation, AbstractImage]:
		"""
		The sprite's image.
		This will return an animation if one is playing.
		Setting an animation via this setter is an error, use
		`animation.play()` for that instead.
		"""
		if self.animation.is_set:
			return self.animation.current
		return self._texture

	@image.setter
	def image(self, image: t.Union[PNFAnimation, AbstractImage]) -> None:
		if isinstance(image, PNFAnimation):
			raise RuntimeError(
				"Please play animations via the sprite's animation controller: "
				"`sprite.animation.play()`"
			)

		self.animation.stop()
		self._set_texture(image.get_texture())

	@property
	def x(self) -> "Numeric":
		"""
		The sprite's x coordinate.
		"""
		return self._x

	@x.setter
	def x(self, x: "Numeric") -> None:
		self._x = x
		self._vertex_list.translate[:] = (x, self._y) * 4

	@property
	def y(self) -> "Numeric":
		"""
		The sprite's y coordinate.
		"""
		return self._y

	@y.setter
	def y(self, y: "Numeric") -> None:
		self._y = y
		self._vertex_list.translate[:] = (self._x, y) * 4

	@property
	def rotation(self) -> "Numeric":
		"""
		The sprite's rotation.
		"""
		return self._rotation

	@rotation.setter
	def rotation(self, rotation: "Numeric") -> None:
		self._rotation = rotation
		self._vertex_list.rotation[:] = (self._rotation, ) * 4

	@property
	def opacity(self) -> "Numeric":
		"""
		The sprite's opacity.
		0 is completely transparent, 255 completely opaque.
		"""
		return self._opacity

	@opacity.setter
	def opacity(self, opacity: "Numeric") -> None:
		self._opacity = opacity
		self._vertex_list.colors[:] = (*self._rgb, int(self._opacity)) * 4

	@property
	def scale(self) -> "Numeric":
		"""
		The sprite's scale along both axes.
		"""
		return self._scale

	@scale.setter
	def scale(self, scale: "Numeric") -> None:
		self._scale = scale
		self._vertex_list.scale[:] = (scale * self._scale_x, scale * self._scale_y) * 4

	@property
	def scale_x(self) -> "Numeric":
		"""
		The sprite's scale along the x axis.
		"""
		return self._scale_x

	@scale_x.setter
	def scale_x(self, scale_x: "Numeric") -> None:
		self._scale_x = scale_x
		self._vertex_list.scale[:] = (self._scale * scale_x, self._scale * self._scale_y) * 4

	@property
	def scale_y(self) -> "Numeric":
		"""
		The sprite's scale along the y axis.
		"""
		return self._scale_y

	@scale_y.setter
	def scale_y(self, scale_y: "Numeric") -> None:
		self._scale_y = scale_y
		self._vertex_list.scale[:] = (self._scale * self._scale_x, self._scale * scale_y) * 4

	@property
	def scroll_factor(self) -> t.Tuple[float, float]:
		"""
		The sprite's scroll factor.
		Determines how hard camera movement will displace the sprite.
		Very useful for parallax effects etc.
		"""
		return self._scroll_factor

	@scroll_factor.setter
	def scroll_factor(self, new_sf: t.Tuple[float, float]) -> None:
		self._scroll_factor = new_sf
		self._vertex_list.scroll_factor[:] = new_sf * 4

	@property
	def color(self) -> t.List[int]:
		"""
		The sprite's color tint.
		This may have wildly varying results if a special shader
		was set.
		"""
		return self._rgb

	@color.setter
	def color(self, color: t.Iterable[int]) -> None:
		self._rgb = list(map(int, color))
		self._vertex_list.colors[:] = (*self._rgb, int(self._opacity)) * 4

	@property
	def visible(self) -> bool:
		"""
		Whether the sprite should be drawn.
		"""
		return self._visible

	@visible.setter
	def visible(self, visible: bool) -> None:
		self._visible = visible
		self._update_position()

	def _set_texture(self, texture):
		prev_h, prev_w = self._texture.height, self._texture.width
		if texture.id is not self._texture.id:
			old_group = self._context.group
			self._context.group = PNFGroup(
				parent = old_group.parent,
				states = self._build_mutators(old_group.program)
			)
			self._vertex_list.delete()
			self._texture = texture
			self._create_vertex_list()
		else:
			self._vertex_list.tex_coords[:] = texture.tex_coords
		self._texture = texture
		# If this is not done, screws over vertices if the texture changes
		# dimension thanks to top left coords
		if prev_h != texture.height or prev_w != texture.width:
			self._update_position()

	def _update_position(self):
		# Contains some manipulations to the creation of position
		# vertices since otherwise the sprite would be displayed
		# upside down
		if not self._visible:
			self._vertex_list.position[:] = (0, 0, 0, 0, 0, 0, 0, 0)
		else:
			img = self._texture
			x1 = -img.anchor_x
			y1 = -img.anchor_y + img.height
			x2 = -img.anchor_x + img.width
			y2 = -img.anchor_y

			if self._subpixel:
				self._vertex_list.position[:] = (x1, y1, x2, y1, x2, y2, x1, y2)
			else:
				self._vertex_list.position[:] = tuple(map(int, (x1, y1, x2, y1, x2, y2, x1, y2)))
