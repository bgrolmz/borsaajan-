namespace BorsaAjani_App.Models;

public enum MentorDecision
{
    Buy,
    Hold,
    Reduce,
    Avoid
}

public enum NewsImpact
{
    Bullish,
    Bearish,
    Neutral
}

public sealed record NewsImpactCard(
    string WhatHappened,
    NewsImpact Impact,
    string WhyItMatters,
    int Confidence
);

public sealed record SimilarScenarioStats(
    int SimilarCases,
    double? WinRatePct,
    double? AvgDrawdownPct
);
