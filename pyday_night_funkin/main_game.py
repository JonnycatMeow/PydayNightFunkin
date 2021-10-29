
from time import time
import typing as t

from loguru import logger
import pyglet
from pyglet.graphics import Batch
import pyglet.media
from pyglet.window import key
from pyglet.window.key import KeyStateHandler

from pyday_night_funkin.config import Config, CONTROL
from pyday_night_funkin.constants import GAME_WIDTH, GAME_HEIGHT
from pyday_night_funkin.debug_pane import DebugPane
from pyday_night_funkin.graphics import PNFWindow
from pyday_night_funkin.key_handler import KeyHandler
from pyday_night_funkin import ogg_decoder
from pyday_night_funkin.scenes import BaseScene, TestScene, TitleScene


__version__ = "0.0.0dev"


class Game():
	def __init__(self) -> None:
		if ogg_decoder not in pyglet.media.get_decoders():
			pyglet.media.add_decoders(ogg_decoder)

		self.debug = True
		# These have to be setup later, see `run`
		self._update_time = 0
		self._fps = None
		self.debug_pane = None

		self.config = Config(
			scroll_speed = 1.0,
			safe_window = 167.0,
			key_bindings = {
				CONTROL.LEFT: [key.LEFT, key.A],
				CONTROL.DOWN: [key.DOWN, key.S],
				CONTROL.UP: [key.UP, key.W],
				CONTROL.RIGHT: [key.RIGHT, key.D],
				CONTROL.ENTER: key.ENTER,
				CONTROL.BACKSPACE: key.BACKSPACE,
				CONTROL.DEBUG_DESYNC: key._1,
			},
		)

		self.window = PNFWindow(
			width = GAME_WIDTH,
			height = GAME_HEIGHT,
			resizable = True,
			vsync = False,
		)

		self.pyglet_ksh = KeyStateHandler()
		self.key_handler = KeyHandler(self.config.key_bindings)

		self.window.push_handlers(self.key_handler)
		self.window.push_handlers(self.pyglet_ksh)
		self.window.push_handlers(on_draw = self.draw)

		self._scene_stack: t.List[BaseScene] = []
		self._scenes_to_draw: t.List[BaseScene] = []
		self._scenes_to_update: t.List[BaseScene] = []

		self._pending_scene_stack_removals = []
		self._pending_scene_stack_additions = []

		self.push_scene(TitleScene)
		# self.push_scene(TestScene)

	def _on_scene_stack_change(self) -> None:
		for self_attr, scene_attr in (
			("_scenes_to_draw", "draw_passthrough"),
			("_scenes_to_update", "update_passthrough"),
		):
			start = len(self._scene_stack) - 1
			while start >= 0 and getattr(self._scene_stack[start], scene_attr):
				start -= 1

			new = self._scene_stack[start:]

			setattr(self, self_attr, new)

	def run(self) -> None:
		"""
		Run the game.
		"""
		# Debug stuff must be set up in the game loop since otherwise the id
		# `1` (something something standard doesn't guarantee it will be 1)
		# will be used twice for two different vertex array objects in 2
		# different contexts? Yeah idk about OpenGL, but it will lead to
		# unexpected errors later when switching scenes and often recreating
		# VAOs.
		logger.remove(0)
		if self.debug:
			def debug_setup(_):
				self._fps = [time() * 1000, 0, "?"]
				self.debug_pane = DebugPane(8)
				logger.add(self.debug_pane.add_message)
				logger.debug(f"Game started (v{__version__}), pyglet version {pyglet.version}")
			pyglet.clock.schedule_once(debug_setup, 0.0)

		pyglet.clock.schedule_interval(self.update, 1 / 80.0)
		pyglet.app.run()

	def push_scene(self, new_scene_cls: t.Type[BaseScene], *args, **kwargs) -> None:
		"""
		Pushes a new scene onto the scene stack which will then
		be the topmost scene.
		The game instance will be passed as the first argument to the
		scene class, with any args and kwargs following it.
		"""
		self._pending_scene_stack_additions.append((new_scene_cls, args, kwargs))

	def remove_scene(self, scene: BaseScene) -> None:
		"""
		Removes the given scene from anywhere in the scene stack.
		ValueError is raised if it is not present.
		"""
		if scene not in self._pending_scene_stack_removals:
			self._pending_scene_stack_removals.append(scene)

	def set_scene(self, new_scene_type: t.Type[BaseScene], *args, **kwargs):
		"""
		Clears the existing scene stack and then sets the given scene
		passed in the same manner as in `push_scene` to be its only
		member.
		"""
		for scene in self._scene_stack:
			if scene not in self._pending_scene_stack_removals:
				self._pending_scene_stack_removals.append(scene)

		self.push_scene(new_scene_type, *args, **kwargs)

	def get_previous_scene(self, scene: BaseScene) -> t.Optional[BaseScene]:
		i = self._scene_stack.index(scene)
		return self._scene_stack[i - 1] if i > 0 else None

	def get_next_scene(self, scene: BaseScene) -> t.Optional[BaseScene]:
		i = self._scene_stack.index(scene)
		return self._scene_stack[i + 1] if i < len(self._scene_stack) - 1 else None

	def draw(self) -> None:
		stime = time()
		self.window.clear()

		for scene in self._scenes_to_draw:
			scene.draw()

		if self.debug:
			self.debug_pane.draw()
			self._fps_bump()
			draw_time = (time() - stime) * 1000
			# Prints frame x-1's draw time in frame x, but who cares
			self.debug_pane.update(self._fps[2], draw_time, self._update_time)

	def update(self, dt: float) -> None:
		stime = time()

		if self._pending_scene_stack_removals:
			while self._pending_scene_stack_removals:
				scene = self._pending_scene_stack_removals.pop()
				self._scene_stack.remove(scene)
				scene.destroy()
			self._on_scene_stack_change()

		if self._pending_scene_stack_additions:
			new_scenes = []
			while self._pending_scene_stack_additions:
				scene_type, args, kwargs = self._pending_scene_stack_additions.pop()
				new_scene = scene_type(self, *args, **kwargs)
				new_scene.creation_args = (args, kwargs)
				new_scenes.append(new_scene)
			# Scene creation may take a long time and cause it to receive an update
			# call with an extremely high dt; delay adding the scene to prevent that.
			def add(_):
				self._scene_stack.extend(new_scenes)
				self._on_scene_stack_change()
			pyglet.clock.schedule_once(add, 0.0)

		for scene in self._scenes_to_update:
			scene.update(dt)

		self._update_time = (time() - stime) * 1000

	def _fps_bump(self):
		self._fps[1] += 1
		t = time() * 1000
		if t - self._fps[0] >= 1000:
			self._fps[0] = t
			self._fps[2] = self._fps[1]
			self._fps[1] = 0
