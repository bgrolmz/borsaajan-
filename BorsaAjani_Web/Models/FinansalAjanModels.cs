using System.Text.Json.Serialization;

namespace BorsaAjani_Web.Models;

// ============================================================================
// FINANCIAL AGENT (/analyze) RESPONSE
// ============================================================================

public class FinansalAnalizYaniti
{
    [JsonPropertyName("success")] public bool Success { get; set; }
    [JsonPropertyName("symbol")] public string? Symbol { get; set; }
    [JsonPropertyName("name")] public string? Name { get; set; }
    [JsonPropertyName("sector")] public string? Sector { get; set; }
    [JsonPropertyName("price")] public double? Price { get; set; }
    [JsonPropertyName("change_pct")] public double? ChangePct { get; set; }
    [JsonPropertyName("analyst_target")] public double? AnalystTarget { get; set; }
    [JsonPropertyName("analyst_recommendation")] public string? AnalystRecommendation { get; set; }
    [JsonPropertyName("analyst_count")] public int? AnalystCount { get; set; }
    [JsonPropertyName("analyst_mean")] public double? AnalystMean { get; set; }

    [JsonPropertyName("targets")] public AnalizTargets? Targets { get; set; }
    [JsonPropertyName("probability")] public AnalizProbability? Probability { get; set; }
    [JsonPropertyName("ev")] public AnalizEV? Ev { get; set; }
    [JsonPropertyName("kelly")] public AnalizKelly? Kelly { get; set; }

    [JsonPropertyName("verdict")] public string? Verdict { get; set; }
    [JsonPropertyName("confidence")] public string? Confidence { get; set; }
    [JsonPropertyName("longshot_warning")] public bool LongshotWarning { get; set; }

    [JsonPropertyName("fundamentals")] public AnalizFundamentals? Fundamentals { get; set; }
    [JsonPropertyName("recent_news")] public List<string>? RecentNews { get; set; }
    [JsonPropertyName("news_enriched")] public List<HaberZenginlestirilmis>? NewsEnriched { get; set; }
    [JsonPropertyName("bull_bear")] public BogaAyiAnalizi? BullBear { get; set; }
    [JsonPropertyName("ai_commentary")] public string? AiCommentary { get; set; }
    [JsonPropertyName("analyzed_at")] public string? AnalyzedAt { get; set; }
    [JsonPropertyName("error")] public string? Error { get; set; }
}

public class AnalizTargets
{
    [JsonPropertyName("entry")] public double Entry { get; set; }
    [JsonPropertyName("target")] public double Target { get; set; }
    [JsonPropertyName("stop_loss")] public double StopLoss { get; set; }
    [JsonPropertyName("upside_pct")] public double UpsidePct { get; set; }
    [JsonPropertyName("stop_pct")] public double StopPct { get; set; }
}

public class AnalizProbability
{
    [JsonPropertyName("initial")] public double Initial { get; set; }
    [JsonPropertyName("after_news")] public double AfterNews { get; set; }
    [JsonPropertyName("bayes_change")] public double? BayesChange { get; set; }
    [JsonPropertyName("news_direction")] public string? NewsDirection { get; set; }
}

public class AnalizEV
{
    [JsonPropertyName("value")] public double Value { get; set; }
    [JsonPropertyName("roi_pct")] public double RoiPct { get; set; }
    [JsonPropertyName("verdict")] public string? Verdict { get; set; }
}

public class AnalizKelly
{
    [JsonPropertyName("full_pct")] public double FullPct { get; set; }
    [JsonPropertyName("quarter_pct")] public double QuarterPct { get; set; }
    [JsonPropertyName("recommended_pct")] public double RecommendedPct { get; set; }
    [JsonPropertyName("dollar_amount")] public double DollarAmount { get; set; }
    [JsonPropertyName("shares")] public int Shares { get; set; }
}

public class AnalizFundamentals
{
    [JsonPropertyName("pe_ratio")] public double? PeRatio { get; set; }
    [JsonPropertyName("eps")] public double? Eps { get; set; }
    [JsonPropertyName("revenue_growth")] public double? RevenueGrowth { get; set; }
    [JsonPropertyName("gross_margins")] public double? GrossMargins { get; set; }
    [JsonPropertyName("debt_to_equity")] public double? DebtToEquity { get; set; }
    [JsonPropertyName("52w_high")] public double? FiftyTwoWeekHigh { get; set; }
    [JsonPropertyName("52w_low")] public double? FiftyTwoWeekLow { get; set; }
}

public class AnalizNews
{
    [JsonPropertyName("title")] public string? Title { get; set; }
    [JsonPropertyName("publisher")] public string? Publisher { get; set; }
    [JsonPropertyName("link")] public string? Link { get; set; }
    [JsonPropertyName("published")] public string? Published { get; set; }
}

public class HaberZenginlestirilmis
{
    [JsonPropertyName("title")] public string? Title { get; set; }
    [JsonPropertyName("summary_tr")] public string? SummaryTr { get; set; }
    [JsonPropertyName("sentiment")] public string? Sentiment { get; set; }
    [JsonPropertyName("impact_emoji")] public string? ImpactEmoji { get; set; }
}

public class BogaAyiAnalizi
{
    [JsonPropertyName("bull_thesis")] public List<string>? BullThesis { get; set; }
    [JsonPropertyName("bear_thesis")] public List<string>? BearThesis { get; set; }
    [JsonPropertyName("balance")] public string? Balance { get; set; }
    [JsonPropertyName("fallback")] public bool Fallback { get; set; }
}

// ============================================================================
// PAPER TRADING DTOs
// ============================================================================

public class PaperPortfolio
{
    [JsonPropertyName("cash")] public double Cash { get; set; }
    [JsonPropertyName("positions_value")] public double PositionsValue { get; set; }
    [JsonPropertyName("total_equity")] public double TotalEquity { get; set; }
    [JsonPropertyName("positions")] public List<PaperPosition>? Positions { get; set; }
    [JsonPropertyName("as_of")] public string? AsOf { get; set; }
}

public class PaperPosition
{
    [JsonPropertyName("symbol")] public string? Symbol { get; set; }
    [JsonPropertyName("shares")] public double Shares { get; set; }
    [JsonPropertyName("avg_cost")] public double AvgCost { get; set; }
    [JsonPropertyName("current_price")] public double CurrentPrice { get; set; }
    [JsonPropertyName("market_value")] public double MarketValue { get; set; }
    [JsonPropertyName("pnl")] public double Pnl { get; set; }
    [JsonPropertyName("pnl_pct")] public double PnlPct { get; set; }
}

public class PaperOrderRequest
{
    [JsonPropertyName("symbol")] public string Symbol { get; set; } = "";
    [JsonPropertyName("shares")] public double Shares { get; set; }
}

public class PaperOrderResult
{
    [JsonPropertyName("success")] public bool Success { get; set; }
    [JsonPropertyName("action")] public string? Action { get; set; }
    [JsonPropertyName("symbol")] public string? Symbol { get; set; }
    [JsonPropertyName("shares")] public double Shares { get; set; }
    [JsonPropertyName("price")] public double Price { get; set; }
    [JsonPropertyName("total")] public double Total { get; set; }
    [JsonPropertyName("pnl")] public double? Pnl { get; set; }
    [JsonPropertyName("cash_remaining")] public double CashRemaining { get; set; }
    [JsonPropertyName("error")] public string? Error { get; set; }
}

public class PaperTrade
{
    [JsonPropertyName("symbol")] public string Symbol { get; set; } = "";
    [JsonPropertyName("action")] public string Action { get; set; } = "";
    [JsonPropertyName("shares")] public double Shares { get; set; }
    [JsonPropertyName("price")] public double Price { get; set; }
    [JsonPropertyName("total")] public double Total { get; set; }
    [JsonPropertyName("pnl")] public double Pnl { get; set; }
    [JsonPropertyName("executed_at")] public string? ExecutedAt { get; set; }
}

public class AnalyzeRequest
{
    [JsonPropertyName("symbol")] public string Symbol { get; set; } = "";
    [JsonPropertyName("portfolio_size")] public double PortfolioSize { get; set; } = 10000;
    [JsonPropertyName("target_upside_pct")] public double TargetUpsidePct { get; set; } = 15.0;
    [JsonPropertyName("stop_loss_pct")] public double StopLossPct { get; set; } = 7.0;
    [JsonPropertyName("prior_probability")] public double? PriorProbability { get; set; }
}
