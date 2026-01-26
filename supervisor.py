#!/usr/bin/env python3
"""
Supervisor script for running arbitrage monitor with auto-restart.

Monitors the main arbitrage detection process and automatically restarts it
if it crashes. Includes restart rate limiting to prevent restart loops.

Usage:
    python supervisor.py

    # Or run in background
    nohup python supervisor.py > supervisor.log 2>&1 &

    # Or use tmux for long-term data collection
    tmux new -s arbitrage
    python supervisor.py
"""

import logging
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [SUPERVISOR] - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("supervisor.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


class ProcessSupervisor:
    """Monitors and restarts child process on failure."""

    def __init__(
        self,
        command,
        max_restarts_per_hour=3,
        restart_delay_seconds=60,
    ):
        self.command = command
        self.max_restarts = max_restarts_per_hour
        self.restart_delay = restart_delay_seconds
        self.restart_history = []
        self.process = None
        self.running = True
        self.pid_file = Path("arbitrage_monitor.pid")
        self.cleanup_done = False  # Prevent duplicate cleanup

    def start(self):
        """Start supervised process with auto-restart."""
        logger.info("=" * 60)
        logger.info("Starting supervisor")
        logger.info(f"Command: {' '.join(self.command)}")
        logger.info(f"Max restarts: {self.max_restarts}/hour")
        logger.info(f"Restart delay: {self.restart_delay}s")
        logger.info(f"PID file: {self.pid_file.absolute()}")
        logger.info("=" * 60)

        # Setup signal handlers
        try:
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
            logger.debug("Signal handlers registered")
        except Exception as e:
            logger.error(f"Failed to register signal handlers: {e}")
            raise

        loop_count = 0
        while self.running:
            loop_count += 1

            if self._too_many_restarts():
                logger.error(
                    f"Too many restarts ({self.max_restarts}/hour limit exceeded). Exiting."
                )
                break

            # Start the process
            try:
                logger.info("Starting monitored process...")
                self.process = subprocess.Popen(
                    self.command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )

                self._write_pid_file()
                logger.info(f"Process started with PID {self.process.pid}")

                # Verify process started successfully
                time.sleep(0.5)  # Give it a moment to fail if it's going to
                if self.process.poll() is not None:
                    exit_code = self.process.returncode
                    logger.error(f"Process failed to start (exit code {exit_code})")
                    self.restart_history.append(datetime.now())
                    if self.running:
                        logger.info(f"Waiting {self.restart_delay}s before restart...")
                        self._interruptible_sleep(self.restart_delay)
                    continue

                # Stream output in real-time
                try:
                    for line in self.process.stdout:
                        if not self.running:
                            break
                        print(line, end='')  # Forward to supervisor's stdout
                except Exception as e:
                    logger.warning(f"Error reading process output: {e}")

                # Wait for process to exit
                exit_code = self.process.wait()

                if exit_code != 0:
                    logger.warning(f"Process exited with code {exit_code}")
                    self.restart_history.append(datetime.now())

                    if self.running:
                        logger.info(f"Waiting {self.restart_delay}s before restart...")
                        self._interruptible_sleep(self.restart_delay)
                else:
                    logger.info("Process exited cleanly (exit code 0)")
                    break

            except KeyboardInterrupt:
                logger.info("Keyboard interrupt in process loop")
                self.running = False
                break
            except Exception as e:
                logger.error(f"Error running process: {e}", exc_info=True)
                self.restart_history.append(datetime.now())
                if self.running:
                    logger.info(f"Waiting {self.restart_delay}s before restart...")
                    self._interruptible_sleep(self.restart_delay)

        # Final cleanup
        try:
            self._cleanup()
        except Exception as e:
            logger.error(f"Error during final cleanup: {e}", exc_info=True)

        logger.info("=" * 60)
        logger.info(f"Supervisor stopped after {loop_count} loop(s)")
        logger.info(f"Total restarts this session: {len(self.restart_history)}")
        logger.info("=" * 60)

    def _too_many_restarts(self):
        """Check if restart rate exceeds threshold."""
        one_hour_ago = datetime.now() - timedelta(hours=1)
        # Clean up old restart history to prevent memory growth
        self.restart_history = [t for t in self.restart_history if t > one_hour_ago]

        if len(self.restart_history) >= self.max_restarts:
            logger.error(
                f"Restart rate exceeded: {len(self.restart_history)} restarts in last hour"
            )
            return True

        return False

    def _interruptible_sleep(self, seconds):
        """Sleep that can be interrupted by self.running flag."""
        for _ in range(int(seconds)):
            if not self.running:
                break
            time.sleep(1)

    def _write_pid_file(self):
        """Write process PID to file."""
        if not self.process:
            return

        try:
            # Check if we can write (disk space, permissions, etc.)
            self.pid_file.write_text(str(self.process.pid))
            logger.debug(f"Wrote PID file: {self.pid_file}")
        except OSError as e:
            logger.error(f"Failed to write PID file (disk full or permissions?): {e}")
        except Exception as e:
            logger.warning(f"Failed to write PID file: {e}")

    def _cleanup(self):
        """Cleanup resources (idempotent - safe to call multiple times)."""
        if self.cleanup_done:
            return

        self.cleanup_done = True
        logger.debug("Starting cleanup...")

        # Terminate child process if still running
        if self.process:
            if self.process.poll() is None:
                logger.info("Terminating child process...")
                try:
                    self.process.terminate()
                    self.process.wait(timeout=1)
                    logger.info("Child process terminated")
                except subprocess.TimeoutExpired:
                    logger.warning("Child process did not terminate, killing...")
                    try:
                        self.process.kill()
                        self.process.wait(timeout=2)
                        logger.info("Child process killed")
                    except Exception as e:
                        logger.error(f"Failed to kill process: {e}")
                except Exception as e:
                    logger.error(f"Error during process termination: {e}")

            # Close stdout to release resources
            try:
                if self.process.stdout:
                    self.process.stdout.close()
            except Exception as e:
                logger.warning(f"Failed to close stdout: {e}")

        # Remove PID file
        if self.pid_file.exists():
            try:
                self.pid_file.unlink()
                logger.debug("Removed PID file")
            except Exception as e:
                logger.warning(f"Failed to remove PID file: {e}")

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        if not self.running:
            # Already shutting down, ignore duplicate signals
            return

        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name}, shutting down...")
        self.running = False

        # Cleanup will be called by the main loop or here if process is running
        if self.process and self.process.poll() is None:
            try:
                self._cleanup()
            except Exception as e:
                logger.error(f"Error during signal handler cleanup: {e}", exc_info=True)


def main():
    """Main entry point."""
    # Command to run the arbitrage monitor
    command = [sys.executable, "-m", "src.main"]

    # Verify Python executable exists
    if not Path(sys.executable).exists():
        logger.error(f"Python executable not found: {sys.executable}")
        sys.exit(1)

    logger.info(f"Python executable: {sys.executable}")

    # Create supervisor
    supervisor = ProcessSupervisor(
        command=command,
        max_restarts_per_hour=3,
        restart_delay_seconds=60,
    )

    # Start monitoring
    exit_code = 0
    try:
        supervisor.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received in main()")
    except Exception as e:
        logger.error(f"Supervisor crashed: {e}", exc_info=True)
        exit_code = 1
    finally:
        logger.info("Supervisor main() exiting")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
