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

    def start(self):
        """Start supervised process with auto-restart."""
        logger.info("Starting supervisor")
        logger.info(f"Command: {' '.join(self.command)}")
        logger.info(f"Max restarts: {self.max_restarts}/hour")

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        while self.running:
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

                # Stream output in real-time
                for line in self.process.stdout:
                    print(line, end='')  # Forward to supervisor's stdout

                # Wait for process to exit
                exit_code = self.process.wait()

                if exit_code != 0:
                    logger.warning(f"Process exited with code {exit_code}")
                    self.restart_history.append(datetime.now())

                    if self.running:
                        logger.info(f"Waiting {self.restart_delay}s before restart...")
                        time.sleep(self.restart_delay)
                else:
                    logger.info("Process exited cleanly (exit code 0)")
                    break

            except Exception as e:
                logger.error(f"Error running process: {e}")
                if self.running:
                    logger.info(f"Waiting {self.restart_delay}s before restart...")
                    time.sleep(self.restart_delay)

        self._cleanup()
        logger.info("Supervisor stopped")

    def _too_many_restarts(self):
        """Check if restart rate exceeds threshold."""
        one_hour_ago = datetime.now() - timedelta(hours=1)
        recent_restarts = [t for t in self.restart_history if t > one_hour_ago]

        if len(recent_restarts) >= self.max_restarts:
            logger.error(
                f"Restart rate exceeded: {len(recent_restarts)} restarts in last hour"
            )
            return True

        return False

    def _write_pid_file(self):
        """Write process PID to file."""
        if self.process:
            try:
                self.pid_file.write_text(str(self.process.pid))
                logger.debug(f"Wrote PID file: {self.pid_file}")
            except Exception as e:
                logger.warning(f"Failed to write PID file: {e}")

    def _cleanup(self):
        """Cleanup resources."""
        # Remove PID file
        if self.pid_file.exists():
            try:
                self.pid_file.unlink()
                logger.debug("Removed PID file")
            except Exception as e:
                logger.warning(f"Failed to remove PID file: {e}")

        # Terminate child process if still running
        if self.process and self.process.poll() is None:
            logger.info("Terminating child process...")
            try:
                self.process.terminate()
                self.process.wait(timeout=1)
                logger.info("Child process terminated")
            except subprocess.TimeoutExpired:
                logger.warning("Child process did not terminate, killing...")
                self.process.kill()
                self.process.wait()
                logger.info("Child process killed")

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name}, shutting down...")
        self.running = False

        # If we're not in the middle of starting a process, trigger cleanup
        if self.process and self.process.poll() is None:
            self._cleanup()


def main():
    """Main entry point."""
    # Command to run the arbitrage monitor
    command = [sys.executable, "-m", "src.main"]

    # Create supervisor
    supervisor = ProcessSupervisor(
        command=command,
        max_restarts_per_hour=3,
        restart_delay_seconds=60,
    )

    # Start monitoring
    try:
        supervisor.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Supervisor crashed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
