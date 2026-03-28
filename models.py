from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class AutocompleteSuggestion:
    term: str
    parent_term: str
    depth: int
    discovered_at: datetime = field(default_factory=datetime.now)


@dataclass
class CandidateNiche:
    term: str
    depth: int
    word_count: int
    autocomplete_branch_count: int = 0
    parent_chain: list[str] = field(default_factory=list)

    @property
    def pre_score(self) -> float:
        wc = self.word_count
        if wc >= 6:
            wc_score = 70
        elif wc == 5:
            wc_score = 90
        elif wc == 4:
            wc_score = 100
        elif wc == 3:
            wc_score = 80
        elif wc == 2:
            wc_score = 40
        else:
            wc_score = 15

        branch_score = min(self.autocomplete_branch_count / 10 * 100, 100)

        if self.depth == 2:
            depth_score = 100
        elif self.depth == 3:
            depth_score = 80
        elif self.depth == 1:
            depth_score = 50
        else:
            depth_score = 30

        return wc_score * 0.3 + branch_score * 0.4 + depth_score * 0.3


@dataclass
class VideoData:
    video_id: str
    title: str
    channel_id: str
    channel_title: str
    published_at: datetime
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    duration_seconds: int = 0

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}" if self.video_id else ""

    @property
    def is_short(self) -> bool:
        """Videos under 90 seconds are likely YouTube Shorts."""
        return self.duration_seconds > 0 and self.duration_seconds < 90


@dataclass
class ChannelData:
    channel_id: str
    title: str
    subscriber_count: int = 0
    video_count: int = 0
    view_count: int = 0

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/channel/{self.channel_id}" if self.channel_id else ""


@dataclass
class NicheScore:
    term: str
    overall_score: float = 0.0
    recency_score: float = 0.0
    velocity_score: float = 0.0
    liquidity_score: float = 0.0
    competition_score: float = 0.0
    specificity_score: float = 0.0
    total_results: int = 0
    videos_last_30d: int = 0
    avg_views: float = 0.0
    avg_views_per_day: float = 0.0
    avg_channel_subs: float = 0.0
    view_to_sub_ratio: float = 0.0
    small_channels_pct: float = 0.0
    best_video: VideoData | None = None
    best_video_channel_subs: int = 0
    videos_analyzed: list[VideoData] = field(default_factory=list)
    channels_analyzed: list[ChannelData] = field(default_factory=list)
    parent_chain: list[str] = field(default_factory=list)
    top_channels: list[str] = field(default_factory=list)  # Channel URLs of top small channels
    evidence_videos: list[str] = field(default_factory=list)  # URLs of top evidence videos
    buying_signal_count: int = 0  # Number of comments with buying intent
    buying_signal_ratio: float = 0.0  # % of comments that are buying signals
    buying_signal_samples: list[str] = field(default_factory=list)  # Sample buying-intent comments
    searched_at: datetime = field(default_factory=datetime.now)
    quota_cost: int = 0


@dataclass
class AIAnalysis:
    term: str
    confidence: str = "unknown"  # high, medium, low, unknown
    quick_rating: int = 0  # 1-5 from pass 1
    quick_reason: str = ""
    opportunity_type: str = ""
    buying_intent_signals: list[str] = field(default_factory=list)
    competition_summary: str = ""
    timing: str = "unknown"  # emerging, growing, peaking, stable, declining
    monetization_angles: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    action_plan: list[str] = field(default_factory=list)
    full_briefing: str = ""
    model_used: str = ""
    tokens_used: int = 0
    analyzed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AgentStep:
    step_number: int
    action: str  # explore_autocomplete, search_youtube, go_deeper, pivot, done
    reasoning: str
    query: str = ""
    findings: str = ""
    next_direction: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TrendSnapshot:
    term: str
    scan_id: int
    overall_score: float = 0.0
    videos_30d: int = 0
    avg_views: float = 0.0
    avg_subs: float = 0.0
    ai_confidence: str = ""
    snapshot_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
