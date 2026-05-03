using System.Text.Json;
using System.Text.Json.Serialization;

namespace BorsaAjani_Web.Models;

public class BorsaYaniti
{
    [JsonPropertyName("sembol")]
    public string? Sembol { get; set; }

    [JsonPropertyName("fiyat_bilgisi")]
    public FiyatBilgisi? Fiyat_Bilgisi { get; set; }

    [JsonPropertyName("piyasa_bilgisi")]
    public PiyasaBilgisi? Piyasa_Bilgisi { get; set; }

    [JsonPropertyName("analiz")]
    public List<AnalizDetay>? Analiz { get; set; }

    [JsonPropertyName("grafik_verileri")]
    public List<GrafikVerisi>? Grafik_Verileri { get; set; }

    [JsonPropertyName("benzer_gecmis_senaryo")]
    public string? Benzer_Gecmis_Senaryo { get; set; }

    [JsonPropertyName("anlik_olay_kontrolu")]
    public string? Anlik_Olay_Kontrolu { get; set; }

    [JsonPropertyName("haber_skoru")]
    public int Haber_Skoru { get; set; }

    [JsonPropertyName("ai_interpreted_news")]
    public List<AiInterpretedNews>? Ai_Interpreted_News { get; set; }

    [JsonPropertyName("adil_deger")]
    public double? Adil_Deger { get; set; }

    [JsonPropertyName("insider_durumu")]
    public string? Insider_Durumu { get; set; }

    [JsonPropertyName("bilanco_tarihi")]
    public string? Bilanco_Tarihi { get; set; }

    [JsonPropertyName("sektor_karsilastirmasi")]
    public string? Sektor_Karsilastirmasi { get; set; }

    [JsonPropertyName("insider_transactions")]
    public List<InsiderTransaction>? Insider_Transactions { get; set; }

    [JsonPropertyName("temel_analiz")]
    public TemelAnaliz? Temel_Analiz { get; set; }

    /// <summary>
    /// master_analysis is stored as raw JsonElement to survive any schema variation
    /// from the backend (503 fallbacks, schema mismatches, etc.).
    /// Use Master_Analysis property for typed access.
    /// </summary>
    [JsonPropertyName("master_analysis")]
    public JsonElement? MasterAnalysisRaw { get; set; }

    [JsonIgnore]
    private MasterAnalysis? _masterAnalysisCached;

    [JsonIgnore]
    public MasterAnalysis? Master_Analysis
    {
        get
        {
            if (_masterAnalysisCached != null) return _masterAnalysisCached;
            if (MasterAnalysisRaw == null || MasterAnalysisRaw.Value.ValueKind == JsonValueKind.Null)
                return null;
            try
            {
                _masterAnalysisCached = MasterAnalysis.ParseSafe(MasterAnalysisRaw.Value);
            }
            catch
            {
                _masterAnalysisCached = null;
            }
            return _masterAnalysisCached;
        }
        set => _masterAnalysisCached = value;
    }
}

public class FiyatBilgisi
{
    [JsonPropertyName("fiyat")]
    public double? Fiyat { get; set; }

    [JsonPropertyName("current_price")]
    public double? Current_Price { get; set; }

    [JsonPropertyName("pre_market_price")]
    public double? Pre_Market_Price { get; set; }

    [JsonPropertyName("post_market_price")]
    public double? Post_Market_Price { get; set; }

    [JsonPropertyName("active_price_type")]
    public string? Active_Price_Type { get; set; }

    [JsonPropertyName("rsi")]
    public double Rsi { get; set; }
    [JsonPropertyName("bb_alt")]
    public double Bb_Alt { get; set; }
    [JsonPropertyName("bb_ust")]
    public double Bb_Ust { get; set; }
    [JsonPropertyName("bb_orta")]
    public double? Bb_Orta { get; set; }
    [JsonPropertyName("macd")]
    public double? Macd { get; set; }
    [JsonPropertyName("macd_signal")]
    public double? Macd_Signal { get; set; }
    [JsonPropertyName("macd_hist")]
    public double? Macd_Hist { get; set; }
    [JsonPropertyName("momentum")]
    public double? Momentum { get; set; }
    [JsonPropertyName("stoch_k")]
    public double? Stoch_K { get; set; }
    [JsonPropertyName("sma20")]
    public double? Sma20 { get; set; }
    [JsonPropertyName("sma50")]
    public double? Sma50 { get; set; }
    [JsonPropertyName("sma200")]
    public double? Sma200 { get; set; }
}

public class PiyasaBilgisi
{
    [JsonPropertyName("vix")]
    public double Vix { get; set; }
    [JsonPropertyName("piyasa_durumu")]
    public string? Piyasa_Durumu { get; set; }
}

public class AnalizDetay
{
    [JsonPropertyName("karar")]
    public string? Karar { get; set; }

    [JsonPropertyName("guven_skoru")]
    public object? Guven_Skoru_Ham { get; set; }

    [JsonIgnore]
    public string Guven_Skoru => Guven_Skoru_Ham?.ToString()?.Replace("%", "") ?? "0";

    [JsonPropertyName("ana_neden")]
    public string? Ana_Neden { get; set; }
    [JsonPropertyName("ozdenetim_yorum")]
    public string? Ozdenetim_Yorum { get; set; }
    [JsonPropertyName("teknik_derinlik")]
    public string? Teknik_Derinlik { get; set; }
    [JsonPropertyName("stratejik_plan")]
    public string? Stratejik_Plan { get; set; }
    [JsonPropertyName("ozel_strateji_basligi")]
    public string? Ozel_Strateji_Basligi { get; set; }
    [JsonPropertyName("ozel_strateji_detayi")]
    public string? Ozel_Strateji_Detayi { get; set; }
    [JsonPropertyName("stop_loss")]
    public string? Stop_Loss { get; set; }
    [JsonPropertyName("risk_uyarisi")]
    public string? Risk_Uyarisi { get; set; }

    [JsonPropertyName("benzer_gecmis_senaryo")]
    public string? Benzer_Gecmis_Senaryo { get; set; }

    [JsonPropertyName("anlik_olay_kontrolu")]
    public string? Anlik_Olay_Kontrolu { get; set; }
}

public class GrafikVerisi
{
    [JsonPropertyName("date")]
    public string? Date { get; set; }

    [JsonPropertyName("open")]
    public double Open { get; set; }

    [JsonPropertyName("high")]
    public double High { get; set; }

    [JsonPropertyName("low")]
    public double Low { get; set; }

    [JsonPropertyName("close")]
    public double Close { get; set; }

    [JsonPropertyName("volume")]
    public long Volume { get; set; }
}

public class TemelAnaliz
{
    [JsonPropertyName("bilanco")]
    public long? Bilanco { get; set; }
}

public class AiInterpretedNews
{
    [JsonPropertyName("title")]
    public string? Title { get; set; }

    [JsonPropertyName("is_critical")]
    public bool Is_Critical { get; set; }

    [JsonPropertyName("priority")]
    public string? Priority { get; set; }

    [JsonPropertyName("impact")]
    public string? Impact { get; set; }

    [JsonPropertyName("explanation")]
    public string? Explanation { get; set; }

    [JsonPropertyName("ai_investor_comment")]
    public string? Ai_Investor_Comment { get; set; }
}

/// <summary>
/// Typed view of master_analysis. Never instantiated by the default deserializer —
/// always built via ParseSafe() which handles every schema variant the backend sends.
/// </summary>
public class MasterAnalysis
{
    public MasterSummary?       Summary              { get; set; }
    public MasterStrategy?      Strategy             { get; set; }
    public MasterFundamental?   FundamentalAnalysis  { get; set; }
    public MasterTechnical?     TechnicalAnalysis    { get; set; }
    public MasterConfidence?    ConfidenceScore      { get; set; }
    public MasterSentiment?     SentimentAndCatalysts{ get; set; }

    // Scenario helpers — backend sends dict OR list, both handled
    public string? BullCaseThesis { get; set; }
    public string? BearCaseThesis { get; set; }

    // ---------------------------------------------------------------
    // Parse a raw JsonElement into a fully typed MasterAnalysis.
    // Every field is read defensively; any missing/wrong-type value
    // is silently skipped so the rest of the object still succeeds.
    // ---------------------------------------------------------------
    public static MasterAnalysis ParseSafe(JsonElement root)
    {
        var ma = new MasterAnalysis();
        if (root.ValueKind != JsonValueKind.Object) return ma;

        // summary
        if (root.TryGetProperty("summary", out var sumEl) && sumEl.ValueKind == JsonValueKind.Object)
        {
            ma.Summary = new MasterSummary
            {
                HeadlineTr  = GetStr(sumEl, "headline_tr"),
                OneLinerTr  = GetStr(sumEl, "one_liner_tr"),
                KeyPointsTr = GetStrList(sumEl, "key_points_tr")
            };
        }

        // strategy
        if (root.TryGetProperty("strategy", out var stEl) && stEl.ValueKind == JsonValueKind.Object)
        {
            MasterRiskManagement? rm = null;
            if (stEl.TryGetProperty("risk_management_tr", out var rmEl) && rmEl.ValueKind == JsonValueKind.Object)
            {
                rm = new MasterRiskManagement
                {
                    PositionSizingTr = GetStr(rmEl, "position_sizing_tr"),
                    StopLoss         = GetStr(rmEl, "stop_loss") ?? GetNum(rmEl, "stop_loss")?.ToString(),
                    TakeProfit       = GetDoubleList(rmEl, "take_profit")
                };
            }
            ma.Strategy = new MasterStrategy
            {
                Stance        = GetStr(stEl, "stance"),
                EntryPlanTr   = GetStrList(stEl, "entry_plan_tr"),
                RiskManagementTr = rm
            };
        }

        // fundamental_analysis
        if (root.TryGetProperty("fundamental_analysis", out var faEl) && faEl.ValueKind == JsonValueKind.Object)
            ma.FundamentalAnalysis = new MasterFundamental { RisksTr = GetStrList(faEl, "risks_tr") };

        // technical_analysis
        if (root.TryGetProperty("technical_analysis", out var taEl) && taEl.ValueKind == JsonValueKind.Object)
            ma.TechnicalAnalysis = new MasterTechnical { NotesTr = GetStrList(taEl, "notes_tr") };

        // confidence_score — may be {"value":75} or plain 75
        if (root.TryGetProperty("confidence_score", out var csEl))
        {
            int val = 0;
            if (csEl.ValueKind == JsonValueKind.Object)
                csEl.TryGetProperty("value", out var vEl); // assigned below via TryGetInt32
            if (csEl.ValueKind == JsonValueKind.Object &&
                csEl.TryGetProperty("value", out var vEl2))
                vEl2.TryGetInt32(out val);
            else if (csEl.ValueKind == JsonValueKind.Number)
                csEl.TryGetInt32(out val);
            ma.ConfidenceScore = new MasterConfidence { Value = val };
        }

        // sentiment_and_catalysts
        if (root.TryGetProperty("sentiment_and_catalysts", out var scEl) && scEl.ValueKind == JsonValueKind.Object)
            ma.SentimentAndCatalysts = new MasterSentiment { NewsImpactTr = GetStr(scEl, "news_impact_tr") };

        // scenarios — dict {"bull_case_tr":{...}} OR list [{type:"bull",...}]
        if (root.TryGetProperty("scenarios", out var scnEl))
        {
            if (scnEl.ValueKind == JsonValueKind.Object)
            {
                ma.BullCaseThesis = GetNestedStr(scnEl, "bull_case_tr", "thesis");
                ma.BearCaseThesis = GetNestedStr(scnEl, "bear_case_tr", "thesis");
            }
            else if (scnEl.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in scnEl.EnumerateArray())
                {
                    var t = GetStr(item, "type") ?? "";
                    var text = GetStr(item, "trigger") ?? GetStr(item, "expected_move") ?? GetStr(item, "description");
                    if (t == "bull") ma.BullCaseThesis = text;
                    else if (t == "bear") ma.BearCaseThesis = text;
                }
            }
        }

        return ma;
    }

    // ---- helpers ----
    private static string? GetStr(JsonElement el, string key)
    {
        try { return el.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null; }
        catch { return null; }
    }

    private static double? GetNum(JsonElement el, string key)
    {
        try { return el.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetDouble() : null; }
        catch { return null; }
    }

    private static string? GetNestedStr(JsonElement el, string key1, string key2)
    {
        try
        {
            if (el.TryGetProperty(key1, out var inner) && inner.ValueKind == JsonValueKind.Object)
                return GetStr(inner, key2);
            return null;
        }
        catch { return null; }
    }

    private static List<string>? GetStrList(JsonElement el, string key)
    {
        try
        {
            if (!el.TryGetProperty(key, out var arr) || arr.ValueKind != JsonValueKind.Array)
                return null;
            var list = new List<string>();
            foreach (var item in arr.EnumerateArray())
                if (item.ValueKind == JsonValueKind.String) list.Add(item.GetString()!);
            return list.Count > 0 ? list : null;
        }
        catch { return null; }
    }

    private static List<double>? GetDoubleList(JsonElement el, string key)
    {
        try
        {
            if (!el.TryGetProperty(key, out var arr)) return null;
            if (arr.ValueKind == JsonValueKind.Array)
            {
                var list = new List<double>();
                foreach (var item in arr.EnumerateArray())
                    if (item.TryGetDouble(out var d)) list.Add(d);
                return list.Count > 0 ? list : null;
            }
            if (arr.ValueKind == JsonValueKind.Number && arr.TryGetDouble(out var single))
                return new List<double> { single };
            return null;
        }
        catch { return null; }
    }
}

public class MasterSummary
{
    public string? HeadlineTr  { get; set; }
    public string? OneLinerTr  { get; set; }
    public List<string>? KeyPointsTr { get; set; }
}

public class MasterStrategy
{
    public string? Stance        { get; set; }
    public List<string>? EntryPlanTr { get; set; }
    public MasterRiskManagement? RiskManagementTr { get; set; }
}

public class MasterRiskManagement
{
    public object? StopLoss          { get; set; }
    public List<double>? TakeProfit  { get; set; }
    public string? PositionSizingTr  { get; set; }
}

public class MasterFundamental
{
    public List<string>? RisksTr { get; set; }
}

public class MasterTechnical
{
    public List<string>? NotesTr { get; set; }
}

public class MasterConfidence
{
    public int Value { get; set; }
}

public class MasterSentiment
{
    public string? NewsImpactTr { get; set; }
}

// Kept for backward-compat (no longer used by deserializer)
public class MasterScenarios
{
    public MasterScenarioCase? BearCaseTr { get; set; }
    public MasterScenarioCase? BullCaseTr { get; set; }
}

public class MasterScenarioCase
{
    public string? Thesis { get; set; }
}

public class InsiderTransaction
{
    [JsonPropertyName("person")]
    public string? Person { get; set; }

    [JsonPropertyName("type")]
    public string? Type { get; set; }

    [JsonPropertyName("shares")]
    public long Shares { get; set; }

    [JsonPropertyName("value")]
    public double? Value { get; set; }

    [JsonPropertyName("date")]
    public string? Date { get; set; }

    [JsonPropertyName("transaction_code")]
    public string? Transaction_Code { get; set; }

    [JsonPropertyName("transaction_type")]
    public string? Transaction_Type { get; set; }
}
