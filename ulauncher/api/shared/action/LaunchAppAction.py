import logging
import os
import re
import shlex
import shutil
import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
# pylint: disable=wrong-import-position
from gi.repository import Gio, GLib

from ulauncher.utils.Settings import Settings
from ulauncher.api.shared.action.BaseAction import BaseAction

logger = logging.getLogger(__name__)
settings = Settings.get_instance()
hasSystemdRun = bool(shutil.which("systemd-run"))


class LaunchAppAction(BaseAction):
    """
    Launches app by given `.desktop` file path

    :param str filename: path to .desktop file
    """

    def __init__(self, filename):
        self.filename = filename

    def keep_app_open(self):
        return False

    def run(self):
        app = Gio.DesktopAppInfo.new_from_filename(self.filename)
        app_id = app.get_id()
        exec = app.get_commandline()
        if not exec:
            logger.error("No command to run %s", self.filename)
        else:
            # strip field codes %f, %F, %u, %U, etc
            sanitized_exec = re.sub(r'\%[uUfFdDnNickvm]', '', exec).rstrip()
            terminal_exec = shlex.split(settings.get_property('terminal-command'))
            if app.get_boolean('Terminal'):
                if terminal_exec:
                    logger.info('Will run command in preferred terminal (%s)', terminal_exec)
                    sanitized_exec = terminal_exec + [sanitized_exec]
                else:
                    sanitized_exec = ['gtk-launch', app_id]
            else:
                sanitized_exec = shlex.split(sanitized_exec)
            if hasSystemdRun and not app.get_boolean('X-Ulauncher-Inherit-Scope'):
                # Escape the Ulauncher cgroup, so this process isn't considered a child process of Ulauncher
                # and doesn't die if Ulauncher dies/crashed/is terminated
                # The slice name is super sensitive and must not contain invalid characters like space
                # or trailing or leading hyphens
                sanitized_app = re.sub(r'(^-*|[^\w^\-^\.]|-*$)', '', app_id)
                sanitized_exec = [
                    'systemd-run',
                    '--user',
                    '--scope',
                    '--slice=app-{}'.format(sanitized_app)
                ] + sanitized_exec

            env = dict(os.environ.items())
            # Make sure GDK apps aren't forced to use x11 on wayland due to ulauncher's need to run
            # under X11 for proper centering.
            env.pop("GDK_BACKEND", None)

            try:
                logger.info('Run application %s (%s) Exec %s', app.get_name(), self.filename, exec)
                envp = ["{}={}".format(k, v) for k, v in env.items()]
                GLib.spawn_async(
                    argv=sanitized_exec,
                    envp=envp,
                    flags=GLib.SpawnFlags.SEARCH_PATH_FROM_ENVP | GLib.SpawnFlags.SEARCH_PATH,
                    # setsid is really only needed if systemd-run is missing, but doesn't hurt to have.
                    child_setup=os.setsid
                )
            except Exception as e:
                logger.error('%s: %s', type(e).__name__, e)
