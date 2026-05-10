namespace BorsaAjani_Web.Services;

public class ChatContextService
{
    private Dictionary<string, object>? _currentContext;
    
    public event Action? ContextChanged;
    
    public Dictionary<string, object>? GetContext()
    {
        return _currentContext;
    }
    
    public void SetStockContext(string symbol, double price, double rsi, double? fairValue, string newsSummary = "")
    {
        _currentContext = new Dictionary<string, object>
        {
            ["type"] = "stock",
            ["symbol"] = symbol,
            ["price"] = price,
            ["rsi"] = rsi,
            ["fair_value"] = fairValue ?? 0,
            ["news_summary"] = newsSummary
        };
        ContextChanged?.Invoke();
    }
    
    public void SetPortfolioContext(double totalValue, double totalPnl, int holdingsCount)
    {
        _currentContext = new Dictionary<string, object>
        {
            ["type"] = "portfolio",
            ["total_value"] = totalValue,
            ["total_pnl"] = totalPnl,
            ["holdings_count"] = holdingsCount
        };
        ContextChanged?.Invoke();
    }
    
    /// <summary>
    /// Store any rich context dict directly (e.g. from BuildMentorContext in HisseAnalizi).
    /// Replaces SetStockContext for callers that already have a full context built.
    /// </summary>
    public void SetRichContext(Dictionary<string, object> ctx)
    {
        _currentContext = ctx;
        ContextChanged?.Invoke();
    }

    public void ClearContext()
    {
        _currentContext = null;
        ContextChanged?.Invoke();
    }
}
