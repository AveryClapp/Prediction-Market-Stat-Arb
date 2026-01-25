"""Rich terminal UI for arbitrage monitor."""

import logging
from collections import deque
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..arbitrage.calculator import ArbitrageOpportunity
from ..clients.base import Market, PlatformStatus
from ..config import CapitalTier, Config
from ..storage.database import HistoricalStats

logger = logging.getLogger(__name__)


# Tier icons matching Discord
TIER_ICONS = {
    "green": "🟢",
    "yellow": "🟡",
    "red": "🔴",
}


class TerminalUI:
    """Rich terminal UI for live arbitrage monitoring."""

    def __init__(self, config: Config):
        """
        Initialize terminal UI.

        Args:
            config: Configuration
        """
        self.config = config
        self.console = Console()

        # State tracking
        self.active_opportunities: list[tuple[Market, Market, ArbitrageOpportunity, CapitalTier]] = []
        self.kalshi_status: Optional[PlatformStatus] = None
        self.polymarket_status: Optional[PlatformStatus] = None
        self.historical_stats: Optional[HistoricalStats] = None
        self.cycle_progress = 0  # 0-60 seconds
        self.logs = deque(maxlen=10)  # Last 10 log messages

        # Live display
        self.live: Optional[Live] = None

    def start(self):
        """Start live display."""
        self.live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=1,
            screen=True,
        )
        self.live.start()

    def stop(self):
        """Stop live display."""
        if self.live:
            self.live.stop()

    def update(self):
        """Update the display."""
        if self.live:
            self.live.update(self._render())

    def add_log(self, message: str):
        """
        Add log message to display.

        Args:
            message: Log message
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[{timestamp}] {message}")

    def set_opportunities(
        self, opportunities: list[tuple[Market, Market, ArbitrageOpportunity, CapitalTier]]
    ):
        """
        Set active opportunities.

        Args:
            opportunities: List of (kalshi_market, poly_market, opportunity, tier)
        """
        self.active_opportunities = opportunities

    def set_platform_status(
        self, kalshi: Optional[PlatformStatus], polymarket: Optional[PlatformStatus]
    ):
        """
        Set platform health status.

        Args:
            kalshi: Kalshi platform status
            polymarket: Polymarket platform status
        """
        self.kalshi_status = kalshi
        self.polymarket_status = polymarket

    def set_historical_stats(self, stats: HistoricalStats):
        """
        Set historical statistics.

        Args:
            stats: Historical stats
        """
        self.historical_stats = stats

    def set_cycle_progress(self, seconds: int):
        """
        Set polling cycle progress.

        Args:
            seconds: Seconds elapsed in current cycle (0-60)
        """
        self.cycle_progress = seconds

    def _render(self) -> Layout:
        """
        Render the full UI layout.

        Returns:
            Rich Layout
        """
        layout = Layout()

        # Split into header and body
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="logs", size=12),
        )

        # Render sections
        layout["header"].update(self._render_header())
        layout["body"].split_row(
            Layout(self._render_opportunities(), name="opportunities"),
            Layout(self._render_stats(), name="stats", ratio=1),
        )
        layout["logs"].update(self._render_logs())

        return layout

    def _render_header(self) -> Panel:
        """Render header with platform status."""
        # Kalshi status
        kalshi_text = "Kalshi: "
        if self.kalshi_status:
            if self.kalshi_status.is_healthy:
                time_ago = ""
                if self.kalshi_status.last_success:
                    delta = (datetime.now() - self.kalshi_status.last_success).total_seconds()
                    time_ago = f" ({int(delta)}s ago)"
                kalshi_text += f"[green]✓{time_ago}[/green]"
            else:
                kalshi_text += f"[red]✗ ({self.kalshi_status.consecutive_failures} failures)[/red]"
        else:
            kalshi_text += "[yellow]...[/yellow]"

        # Polymarket status
        poly_text = "Polymarket: "
        if self.polymarket_status:
            if self.polymarket_status.is_healthy:
                time_ago = ""
                if self.polymarket_status.last_success:
                    delta = (datetime.now() - self.polymarket_status.last_success).total_seconds()
                    time_ago = f" ({int(delta)}s ago)"
                poly_text += f"[green]✓{time_ago}[/green]"
            else:
                poly_text += f"[red]✗ ({self.polymarket_status.consecutive_failures} failures)[/red]"
        else:
            poly_text += "[yellow]...[/yellow]"

        # Cycle progress
        cycle_text = f"Cycle: {self.cycle_progress}/{self.config.polling.interval_seconds}s"

        header_text = f"{kalshi_text} | {poly_text} | {cycle_text}"

        return Panel(
            Text.from_markup(header_text),
            title="Prediction Market Arbitrage Monitor",
            border_style="blue",
        )

    def _render_opportunities(self) -> Panel:
        """Render active opportunities table."""
        table = Table(title=f"Active Opportunities ({len(self.active_opportunities)})")

        table.add_column("Tier", style="bold", width=4)
        table.add_column("Event", style="cyan", max_width=40)
        table.add_column("Profit", justify="right", style="green")
        table.add_column("Capital", justify="right")
        table.add_column("Kalshi", justify="right")
        table.add_column("Poly", justify="right")

        for kalshi_market, poly_market, opportunity, tier in self.active_opportunities:
            icon = TIER_ICONS.get(tier.color, "⚪")
            tier_label = f"{icon} {tier.name[0]}"

            # Truncate event description
            event = kalshi_market.description
            if len(event) > 37:
                event = event[:37] + "..."

            # Format values
            profit = f"{opportunity.net_profit_pct:.1f}%"
            capital = f"${opportunity.required_capital:,.0f}"
            kalshi_price = f"{opportunity.kalshi_price:.2f}"
            poly_price = f"{opportunity.polymarket_price:.2f}"

            table.add_row(
                tier_label,
                event,
                profit,
                capital,
                kalshi_price,
                poly_price,
            )

        if not self.active_opportunities:
            table.add_row("", "No opportunities found", "", "", "", "")

        return Panel(table, border_style="green")

    def _render_stats(self) -> Panel:
        """Render historical statistics."""
        if not self.historical_stats:
            text = "Loading statistics..."
        else:
            text = (
                f"[bold]Historical Stats[/bold]\n\n"
                f"Total opportunities: {self.historical_stats.total_opportunities}\n"
                f"Total potential profit: ${self.historical_stats.total_potential_profit:,.2f}\n"
                f"Average profit: {self.historical_stats.average_profit_pct:.2f}%"
            )

        return Panel(Text.from_markup(text), title="Stats", border_style="yellow")

    def _render_logs(self) -> Panel:
        """Render recent logs."""
        if not self.logs:
            log_text = "No logs yet..."
        else:
            log_text = "\n".join(self.logs)

        return Panel(
            Text(log_text, style="dim"),
            title="Recent Activity",
            border_style="blue",
        )
