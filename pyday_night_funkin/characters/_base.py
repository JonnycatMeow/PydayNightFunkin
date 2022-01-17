
import typing as t

from pyglet.math import Vec2

from pyday_night_funkin.enums import ANIMATION_TAG
from pyday_night_funkin.core.pnf_sprite import PNFSprite

if t.TYPE_CHECKING:
	from pyday_night_funkin.scenes import MusicBeatScene
	from pyday_night_funkin.types import Numeric


class Character(PNFSprite):
	"""
	A beloved character that moves, sings and... well I guess that's
	about it. Holds some more information than a generic sprite which
	is related to the character via static `get_` methods.
	"""

	def __init__(self, scene: "MusicBeatScene", *args, **kwargs) -> None:
		super().__init__(*args, **kwargs)

		self.scene = scene
		self._hold_timeout = self.get_hold_timeout()
		self.hold_timer = 0.0
		self.dont_idle = False

	def update(self, dt: float) -> None:
		super().update(dt)
		if (
			self.animation.has_tag(ANIMATION_TAG.SING) or
			self.animation.has_tag(ANIMATION_TAG.MISS)
		):
			self.hold_timer += dt

		if (
			self.hold_timer >= self._hold_timeout * self.scene.conductor.step_duration * 0.001 and
			not self.dont_idle
		):
			self.hold_timer = 0.0
			self.dance()

	def dance(self) -> None:
		"""
		Make the character play their idle animation.
		Subclassable for characters that alternate between dancing
		poses, by default just plays an animation called `idle`.
		"""
		self.animation.play("idle")

	@staticmethod
	def get_hold_timeout() -> "Numeric":
		"""
		Returns how many steps the character should remain in their
		sing animation for after singing a note. Default is 4.
		"""
		return 4

	@staticmethod
	def get_story_menu_transform() -> t.Tuple[Vec2, float]:
		"""
		Returns a two-element tuple of the translation and scale the
		character should undergo when its `story_menu` animation is
		displayed. Default is a null vector and 1.
		"""
		return (Vec2(0, 0), 1)

	@staticmethod
	def get_string() -> str:
		"""
		Each character has a string assigned to them used to gather
		information for them, i. e. the health icon.
		This method returns that string. Default is `''`.
		"""
		return ""


class FlipIdleCharacter(Character):
	"""
	Character that does not play the `idle` animation in their
	`dance` function but instead alternates between `idle_left`
	and `idle_right` each invocation.
	"""

	_dance_right = False

	def dance(self) -> None:
		self._dance_right = not self._dance_right
		self.animation.play("idle_right" if self._dance_right else "idle_left")
