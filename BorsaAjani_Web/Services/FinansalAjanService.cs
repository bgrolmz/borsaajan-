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
}
