
import typing as t
from pyglet.image import Animation
from pyglet.math import Vec2


if t.TYPE_CHECKING:
	from pyglet.image import Texture
	from pyday_night_funkin.graphics.pnf_sprite import PNFSprite
	from pyday_night_funkin.image_loader import FrameInfoTexture


class OffsetAnimationFrame():
	"""
	Similar to pyglet's AnimationFrame, except it also receives
	per-frame offset information a total offset is calculated from
	that should be applied to its receiving sprite's x and y
	coordinates.
	"""

	__slots__ = ("image", "duration", "frame_info")

	def __init__(
		self,
		image: "Texture",
		duration: float,
		frame_info: t.Tuple[int, int, int, int],
	) -> None:
		self.image = image
		self.duration = duration
		self.frame_info = frame_info

	def __repr__(self):
		return (
			f"OffsetAnimationFrame({self.image}, duration={self.duration}, "
			f"frame_info={self.frame_info})"
		)


class PNFAnimation(Animation):
	"""
	Pyglet animation subclass to expand its functionality.
	"""

	def __init__(
		self,
		frames: t.Sequence[OffsetAnimationFrame],
		loop: bool = False,
		offset: t.Optional[Vec2] = None,
		*tags: t.Hashable,
	):
		"""
		Creates a PNFAnimation.
		"""
		super().__init__(frames)

		self.offset = offset
		self.loop = loop
		self.tags = set(tags)


class AnimationController():
	def __init__(self) -> None:
		self._animations: t.Dict[str, PNFAnimation] = {}
		self.playing: bool = False
		self.current: t.Optional[PNFAnimation] = None
		self.current_name = None
		self._base_box = None
		self._frame_idx = 0
		self._next_dt = 0.0
		# Offset of current animation frame, calculated with animation frame
		# dimensions, frame info and 
		# Not final, still needs the sprite's scale.
		self._frame_offset = Vec2()

		self._new_offset = None
		self._new_texture = None

	def _get_post_animate_offset(self) -> Vec2:
		"""
		"""
		fix, fiy, fiw, fih = self.current_frame.frame_info
		new_frame_offset = Vec2(
			round(fix - (self._base_box[0] - fiw) // 2),
			round(fiy - (self._base_box[1] - fih) // 2),
		)
		old_frame_offset = self._frame_offset
		self._frame_offset = new_frame_offset
		return old_frame_offset - new_frame_offset

	def _set_base_box(
		self, what: t.Union[PNFAnimation, OffsetAnimationFrame, Vec2],
	) -> None:
		if not isinstance(what, Vec2):
			if not isinstance(what, OffsetAnimationFrame):
				if not isinstance(what, PNFAnimation):
					raise TypeError("Invalid type.")
				frame = what.frames[0]
			else:
				frame = what
			new_bb = Vec2(
				frame.frame_info[2] - frame.frame_info[0],
				frame.frame_info[3] - frame.frame_info[1],
			)
		else:
			new_bb = what
		self._base_box = new_bb

	def _set_frame(self, frame: "Texture") -> None:
		self._new_texture = frame

	def _set_offset(self, offset: Vec2) -> None:
		if self._new_offset is None:
			self._new_offset = offset
		else:
			self._new_offset += offset

	def query_new_frame(self) -> t.Optional["Texture"]:
		r = self._new_texture
		self._new_texture = None
		return r

	def query_new_offset(self) -> t.Optional[Vec2]:
		r = self._new_offset
		self._new_offset = None
		return r

	def _detach_animation(self) -> Vec2:
		offset_delta = self._frame_offset
		if self.current.offset is not None:
			offset_delta += self.current.offset

		self._frame_offset = Vec2()

		self.playing = False
		self.current = self.current_name = None

		return offset_delta

	def _on_new_frame(self) -> None:
		self._set_frame(self.current_frame.image.get_texture())
		self._set_offset(self._get_post_animate_offset())

	@property
	def current_frame(self) -> t.Optional[OffsetAnimationFrame]:
		"""
		Returns the current animation's frame or `None` if no animation
		is playing.
		"""
		if self.current is None:
			return None
		return self.current.frames[self._frame_idx]

	def update(self, dt: float) -> None:
		"""
		"""
		if not self.playing:
			return

		_next_dt = self._next_dt
		frame_changed = False
		while dt > _next_dt:
			dt -= _next_dt
			if self._frame_idx >= len(self.current.frames) - 1:
				# Animation has ended
				if self.current.loop:
					self._frame_idx = -1
				else:
					self.playing = False
					return
			self._frame_idx += 1
			frame_changed = True
			_next_dt = self.current.frames[self._frame_idx].duration

		_next_dt -= dt
		if frame_changed:
			self._on_new_frame()

		self._next_dt = _next_dt

	def add(
		self,
		name: str,
		anim_data: t.Union[PNFAnimation, t.Sequence["FrameInfoTexture"]],
		fps: float = 24.0,
		loop: bool = False,
		offset: t.Optional[t.Union[t.Tuple[int, int], Vec2]] = None,
		*tags: t.Hashable,
	) -> None:
		"""
		Adds an animation to this AnimationController.
		If no base box exists yet it will be set on the base of this
		animation, so try to choose a neutral animation as the first
		one.
		"""
		if fps <= 0:
			raise ValueError("FPS can't be equal to or less than 0!")

		if offset is not None and not isinstance(offset, Vec2):
			offset = Vec2(*offset)

		spf = 1.0 / fps
		if isinstance(anim_data, PNFAnimation):
			animation = anim_data
		else:
			frames = [
				OffsetAnimationFrame(tex.texture, spf, tex.frame_info)
				for tex in anim_data
			]
			animation = PNFAnimation(frames, loop, offset, *tags)

		self._animations[name] = animation
		if self._base_box is None:
			self._set_base_box(animation)

	def play(self, name: str, force: bool = False) -> None:
		if (
			self.current is not None and
			self.current_name == name and not force
		):
			if not self.playing:
				self.playing = True
			return

		# Remove old animation and its offsets
		offset_delta = Vec2()
		if self.current is not None:
			offset_delta += self._detach_animation()

		# Set some variables for new animation
		self.current = self._animations[name]
		self.current_name = name
		self._frame_idx = 0
		self.playing = True

		# Add new animation's offset
		if self.current.offset is not None:
			offset_delta -= self.current.offset
			self._set_base_box(self.current)

		# Set first frame
		frame = self.current.frames[0]
		self._next_dt = frame.duration
		self._set_offset(offset_delta)
		self._on_new_frame()

	def pause(self) -> None:
		pass

	def stop(self) -> None:
		pass
