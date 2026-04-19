using System.Text.Json.Serialization;

namespace BorsaAjani_App.Models;

public sealed class PortfolioListResponse
{
    [JsonPropertyName("success")] public bool Success { get; set; }
    [JsonPropertyName("portfolio")] public List<PortfolioItemDto>? Portfolio { get; set; }
    [JsonPropertyName("count")] public int Count { get; set; }
    [JsonPropertyName("message")] public string? Message { get; set; }
}

public sealed class PortfolioItemDto
{
    [JsonPropertyName("symbol")] public string? Symbol { get; set; }
    [JsonPropertyName("avg_cost")] public double Avg_Cost { get; set; }
    [JsonPropertyName("quantity")] public double Quantity { get; set; }
}

public sealed class PortfolioAddResponse
{
    [JsonPropertyName("success")] public bool Success { get; set; }
    [JsonPropertyName("message")] public string? Message { get; set; }
}
