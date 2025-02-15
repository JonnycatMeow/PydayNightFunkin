
import queue

from pyglet import font

import pyday_night_funkin.constants as CNST
from pyday_night_funkin.core.camera import Camera
from pyday_night_funkin.core.graphics import PNFBatch, PNFGroup
from pyday_night_funkin.core.pnf_text import PNFText
from pyday_night_funkin.core.pnf_sprite import PNFSprite
from pyday_night_funkin.core.scene import SceneContext
from pyday_night_funkin.core.utils import to_rgba_tuple


class DebugPane:
	"""
	Shoddy class to manage text lines on a rectangle, used to display
	debug messages and fps.
	"""

	FONT_SIZE = 8
	FPS_FONT_SIZE = 12
	LINE_DIST = 2
	PADDING = 8

	def __init__(self, line_amount: int) -> None:
		# NOTE: This uses PNF graphics, but is not a scene,
		# so update, tweens and all other good stuff won't work.
		self.insert_index = 0
		self.background = PNFGroup(order=0)
		self.foreground = PNFGroup(order=1)
		self.batch = PNFBatch()
		self._queue = queue.Queue()
		self.labels = [
			PNFText(
				x = 10,
				y = (self.FONT_SIZE * i + self.LINE_DIST * i),
				font_name = "Consolas",
				font_size = self.FONT_SIZE,
				context = SceneContext(self.batch, self.foreground),
			) for i in range(line_amount)
		]
		self.fps_label = PNFText(
			x = 10,
			y = ((self.FONT_SIZE * (line_amount + 1)) + 4 + self.LINE_DIST * line_amount),
			font_name = "Consolas",
			font_size = self.FPS_FONT_SIZE,
			multiline = True,
			context = SceneContext(self.batch, self.foreground),
		)
		self.debug_rect = PNFSprite(
			x = self.PADDING,
			y = 0,
			context = SceneContext(self.batch, self.background),
		)
		self.debug_rect.make_rect(
			to_rgba_tuple(0x2020AA64),
			CNST.GAME_WIDTH - 2 * self.PADDING,
			(self.FONT_SIZE * (line_amount + 1)) + (self.LINE_DIST * (line_amount - 1)),
		)

		self.fps_rect = PNFSprite(
			x = self.PADDING,
			y = self.fps_label.y - self.LINE_DIST,
			context = SceneContext(self.batch, self.background),
		)
		# HACK getting the ascent like this
		bluegh = font.load("Consolas", self.FPS_FONT_SIZE).ascent
		self.fps_rect.make_rect(
			to_rgba_tuple(0x7F7F7F7F),
			CNST.GAME_WIDTH // 3,
			(bluegh * 4) + self.LINE_DIST * 2,
		)

	def add_message(self, log_message: str) -> None:
		"""
		Adds the given log message to the debug pane's queue.
		This should be thread-safe, but the change will only appear
		once `update` is called.
		"""
		self._queue.put(log_message)

	def update(
		self,
		fps: int,
		frame_avg: float,
		frame_max: float,
		update_avg: float,
		update_max: float,
		draw_avg: float,
		draw_max: float,
		draw_time: float,
		update_time: float,
	) -> None:
		"""
		Updates the debug pane and writes all queued messages to
		the labels, causing a possibly overflowing label's text to be
		deleted and bumping up all other labels.
		Additionally, sets the fps label's text to a readable string
		built from the supplied fps, draw time and update time.
		Call this when GL allows it, there have been weird threading
		errors in the past.
		"""
		self.fps_label.text = (
			f"FPS:    {fps:>3}\n"
			f"FRAME:  avg {frame_avg:>4.1f}, max {frame_max:>5.1f}, "
			f"cur {draw_time + update_time:>5.1f}\n"
			f"UPDATE: avg {update_avg:>4.1f}, max {update_max:>5.1f}, cur {update_time:>5.1f}\n"
			f"DRAW:   avg {draw_avg:>4.1f}, max {draw_max:>5.1f}, cur {draw_time:>5.1f}"
		)

		if self._queue.empty():
			return

		while True:
			try:
				message = self._queue.get_nowait()
			except queue.Empty:
				break

			if self.insert_index == len(self.labels):
				self.insert_index -= 1
				for i in range(len(self.labels) - 1):
					self.labels[i].text = self.labels[i + 1].text

			self.labels[self.insert_index].text = message
			self.insert_index += 1

	def draw(self):
		"""
		Draws the DebugPane.
		"""
		self.batch.draw(Camera.get_dummy())
