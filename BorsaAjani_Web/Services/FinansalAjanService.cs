using System.Net.Http.Json;
using System.Text.Json;
using BorsaAjani_Web.Models;

namespace BorsaAjani_Web.Services;

/// <summary>
/// Wraps backend Financial Agent + Paper Trading endpoints.
/// Uses the named "BackendApi" HttpClient registered in Program.cs.
/// </summary>
public class FinansalAjanService
{
    private readonly IHttpClientFactory _httpFactory;
    private readonly ILogger<FinansalAjanService> _logger;

    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNameCaseInsensitive = true
    };

    public FinansalAjanService(IHttpClientFactory httpFactory, ILogger<FinansalAjanService> logger)
    {
        _httpFactory = httpFactory;
        _logger = logger;
    }

    private HttpClient Client => _httpFactory.CreateClient("BackendApi");

    // ────────────────────────────────────────────────────────────
    // ANALYZE
    // ────────────────────────────────────────────────────────────

    public async Task<FinansalAnalizYaniti?> AnalyzeAsync(AnalyzeRequest req, CancellationToken ct = default)
    {
        try
        {
            var resp = await Client.PostAsJsonAsync("/analyze", req, JsonOpts, ct);
            if (!resp.IsSuccessStatusCode)
            {
                var err = await resp.Content.ReadAsStringAsync(ct);
                _logger.LogWarning("Analyze failed {Code}: {Err}", resp.StatusCode, err);
                return new FinansalAnalizYaniti { Success = false, Error = $"HTTP {(int)resp.StatusCode}: {err}" };
            }
            return await resp.Content.ReadFromJsonAsync<FinansalAnalizYaniti>(JsonOpts, ct);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Analyze exception");
            return new FinansalAnalizYaniti { Success = false, Error = ex.Message };
        }
    }

    // ────────────────────────────────────────────────────────────
    // PAPER TRADING
    // ────────────────────────────────────────────────────────────

    public async Task<PaperPortfolio?> GetPortfolioAsync(CancellationToken ct = default)
    {
        try
        {
            return await Client.GetFromJsonAsync<PaperPortfolio>("/paper/portfolio", JsonOpts, ct);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "GetPortfolio exception");
            return null;
        }
    }

    public async Task<PaperOrderResult> BuyAsync(string symbol, double shares, CancellationToken ct = default)
    {
        return await PostOrderAsync("/paper/buy", symbol, shares, ct);
    }

    public async Task<PaperOrderResult> SellAsync(string symbol, double shares, CancellationToken ct = default)
    {
        return await PostOrderAsync("/paper/sell", symbol, shares, ct);
    }

    private async Task<PaperOrderResult> PostOrderAsync(string url, string symbol, double shares, CancellationToken ct)
    {
        try
        {
            var body = new PaperOrderRequest { Symbol = symbol, Shares = shares };
            var resp = await Client.PostAsJsonAsync(url, body, JsonOpts, ct);
            var json = await resp.Content.ReadAsStringAsync(ct);

            if (!resp.IsSuccessStatusCode)
            {
                _logger.LogWarning("Order failed {Code}: {Err}", resp.StatusCode, json);
                // FastAPI returns {"detail":"..."} on HTTPException
                string err = json;
                try
                {
                    using var doc = JsonDocument.Parse(json);
                    if (doc.RootElement.TryGetProperty("detail", out var d))
                        err = d.GetString() ?? json;
                }
                catch { }
                return new PaperOrderResult { Success = false, Error = err };
            }
            return JsonSerializer.Deserialize<PaperOrderResult>(json, JsonOpts)
                   ?? new PaperOrderResult { Success = false, Error = "Empty response" };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Order exception");
            return new PaperOrderResult { Success = false, Error = ex.Message };
        }
    }

    public async Task<List<PaperTrade>> GetTradesAsync(int limit = 200, CancellationToken ct = default)
    {
        try
        {
            var resp = await Client.GetAsync($"/paper/trades?limit={limit}", ct);
            if (!resp.IsSuccessStatusCode) return new();
            var json = await resp.Content.ReadAsStringAsync(ct);
            using var doc = JsonDocument.Parse(json);
            if (!doc.RootElement.TryGetProperty("trades", out var arr)) return new();
            var list = new List<PaperTrade>();
            foreach (var el in arr.EnumerateArray())
            {
                list.Add(new PaperTrade
                {
                    Symbol = el.TryGetProperty("symbol", out var s) ? s.GetString() ?? "" : "",
                    Action = el.TryGetProperty("action", out var a) ? a.GetString() ?? "" : "",
                    Shares = el.TryGetProperty("shares", out var sh) && sh.ValueKind == JsonValueKind.Number ? sh.GetDouble() : 0,
                    Price = el.TryGetProperty("price", out var pr) && pr.ValueKind == JsonValueKind.Number ? pr.GetDouble() : 0,
                    Total = el.TryGetProperty("total", out var t) && t.ValueKind == JsonValueKind.Number ? t.GetDouble() : 0,
                    Pnl = el.TryGetProperty("pnl", out var pn) && pn.ValueKind == JsonValueKind.Number ? pn.GetDouble() : 0,
                    ExecutedAt = el.TryGetProperty("executed_at", out var e) ? e.GetString() : null,
                });
            }
            return list;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "GetTrades exception");
            return new();
        }
    }

    public async Task<bool> ResetPortfolioAsync(double startingCash = 100000.0, CancellationToken ct = default)
    {
        try
        {
            var resp = await Client.PostAsync($"/paper/reset?starting_cash={startingCash}", null, ct);
            return resp.IsSuccessStatusCode;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Reset exception");
            return false;
        }
    }

    // ────────────────────────────────────────────────────────────
    // WATCHLIST
    // ────────────────────────────────────────────────────────────

    public async Task<List<WatchlistItem>?> GetWatchlistAsync(CancellationToken ct = default)
    {
        try
        {
            var resp = await Client.GetAsync("/hermes/watchlist", ct);
            if (!resp.IsSuccessStatusCode) return new List<WatchlistItem>();
            var json = await resp.Content.ReadAsStringAsync(ct);
            using var doc = JsonDocument.Parse(json);
            if (!doc.RootElement.TryGetProperty("watchlist", out var arr)) return new List<WatchlistItem>();
            var items = new List<WatchlistItem>();
            foreach (var el in arr.EnumerateArray())
            {
                items.Add(new WatchlistItem
                {
                    Symbol = el.TryGetProperty("symbol", out var s) ? s.GetString() : null,
                    Mode = el.TryGetProperty("mode", out var m) ? m.GetString() : "STOCK",
                    AddedAt = el.TryGetProperty("added_at", out var a) ? a.GetString()
                            : (el.TryGetProperty("created_at", out var ca) ? ca.GetString() : null),
                });
            }
            return items;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "GetWatchlist exception");
            return null;
        }
    }

    public async Task<bool> AddWatchlistAsync(string symbol, string mode = "STOCK", CancellationToken ct = default)
    {
        try
        {
            var resp = await Client.PostAsync($"/hermes/watchlist/add?symbol={Uri.EscapeDataString(symbol)}&mode={mode}", null, ct);
            return resp.IsSuccessStatusCode;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "AddWatchlist exception");
            return false;
        }
    }

    public async Task<bool> RemoveWatchlistAsync(string symbol, CancellationToken ct = default)
    {
        try
        {
            var resp = await Client.DeleteAsync($"/watchlist/{Uri.EscapeDataString(symbol)}", ct);
            return resp.IsSuccessStatusCode;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "RemoveWatchlist exception");
            return false;
        }
    }

    // ────────────────────────────────────────────────────────────
    // ANALYSIS HISTORY
    // ────────────────────────────────────────────────────────────

    public async Task<List<HistoryItem>?> GetHistoryAsync(CancellationToken ct = default)
    {
        try
        {
            var resp = await Client.GetAsync("/history/all", ct);
            if (!resp.IsSuccessStatusCode) return new List<HistoryItem>();
            var json = await resp.Content.ReadAsStringAsync(ct);
            using var doc = JsonDocument.Parse(json);
            if (!doc.RootElement.TryGetProperty("history", out var arr)) return new List<HistoryItem>();
            var items = new List<HistoryItem>();
            foreach (var el in arr.EnumerateArray())
            {
                items.Add(new HistoryItem
                {
                    Id = el.TryGetProperty("id", out var id) && id.ValueKind == JsonValueKind.Number ? id.GetInt64() : 0,
                    Symbol = el.TryGetProperty("symbol", out var s) ? s.GetString() : null,
                    Mode = el.TryGetProperty("mode", out var m) ? m.GetString() : null,
                    Summary = el.TryGetProperty("summary", out var sm) ? sm.GetString() : null,
                    RiskLevel = el.TryGetProperty("risk_level", out var r) ? (r.ValueKind == JsonValueKind.Number ? r.GetInt32().ToString() : r.GetString()) : null,
                    PriceAtAnalysis = el.TryGetProperty("price_at_analysis", out var p) && p.ValueKind == JsonValueKind.Number ? p.GetDouble() : (double?)null,
                    CreatedAt = el.TryGetProperty("created_at", out var c) ? c.GetString() : null,
                });
            }
            return items;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "GetHistory exception");
            return null;
        }
    }
}

public class WatchlistItem
{
    public string? Symbol { get; set; }
    public string? Mode { get; set; }
    public string? AddedAt { get; set; }
}

public class HistoryItem
{
    public long Id { get; set; }
    public string? Symbol { get; set; }
    public string? Mode { get; set; }
    public string? Summary { get; set; }
    public string? RiskLevel { get; set; }
    public double? PriceAtAnalysis { get; set; }
    public string? CreatedAt { get; set; }
}

