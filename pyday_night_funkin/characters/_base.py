
import typing as t

from pyday_night_funkin.enums import ANIMATION_TAG
from pyday_night_funkin.core.pnf_sprite import PNFSprite

if t.TYPE_CHECKING:
	from pyday_night_funkin.scenes import MusicBeatScene
	from pyday_night_funkin.types import Numeric


class Character(PNFSprite):

	def __init__(self, scene: "MusicBeatScene", *args, **kwargs) -> None:
		super().__init__(*args, **kwargs)

		self.scene = scene
		self._hold_timeout = self.get_hold_timeout()
		self.hold_timer = 0.0
		self.dont_idle = False

	def update(self, dt: float) -> None:
		super().update(dt)
		if self.animation.has_tag(ANIMATION_TAG.SING):
			self.hold_timer += dt

		if (
			self.hold_timer >= self._hold_timeout * self.scene.conductor.step_duration * 0.001 and
			not self.dont_idle
		):
			self.hold_timer = 0.0
			self.animation.play("idle_bop")

	@staticmethod
	def get_hold_timeout() -> "Numeric":
		"""
		Returns how many steps the character should remain in their
		sing animation for after singing a note. Default is 4.
		"""
		return 4
