using System.Text.Json.Serialization;
using System.Text.Json;

namespace BorsaAjani_App.Models;

public class BorsaYaniti
{
    [JsonPropertyName("sembol")]
    public string? Sembol { get; set; }

    [JsonPropertyName("fiyat_bilgisi")]
    public FiyatBilgisi? Fiyat_Bilgisi { get; set; }

    [JsonPropertyName("piyasa_bilgisi")]
    public PiyasaBilgisi? Piyasa_Bilgisi { get; set; }

    // BURASI LİSTE OLDU, ARTIK PYTHON NE YOLLARSA KABUL
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

    [JsonPropertyName("adil_deger")]
    public double? Adil_Deger { get; set; }

    [JsonPropertyName("insider_durumu")]
    public string? Insider_Durumu { get; set; }

    [JsonPropertyName("bilanco_tarihi")]
    public string? Bilanco_Tarihi { get; set; }

    [JsonPropertyName("sektor_karsilastirmasi")]
    public string? Sektor_Karsilastirmasi { get; set; }

    [JsonPropertyName("temel_analiz")]
    public TemelAnaliz? Temel_Analiz { get; set; }

    // New format (nested, structured) included by backend for forward-compatibility.
    // We keep it as JsonElement to avoid breaking changes if schema evolves.
    [JsonPropertyName("master_analysis")]
    public JsonElement? Master_Analysis { get; set; }

    // Capture any additional fields returned by backend without failing deserialization.
    [JsonExtensionData]
    public Dictionary<string, JsonElement>? Extra { get; set; }

    // Present on /market-data/{sembol}. Not always included on /analiz/{sembol}.
    [JsonPropertyName("ai_interpreted_news")]
    public List<AiInterpretedNewsItem>? Ai_Interpreted_News { get; set; }
}

public class FiyatBilgisi
{
    [JsonPropertyName("fiyat")]
    public double Fiyat { get; set; }
    [JsonPropertyName("rsi")]
    public double Rsi { get; set; }
    [JsonPropertyName("bb_alt")]
    public double Bb_Alt { get; set; }
    [JsonPropertyName("bb_ust")]
    public double Bb_Ust { get; set; }
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

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? Extra { get; set; }
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

public class AiInterpretedNewsItem
{
    [JsonPropertyName("title")]
    public string? Title { get; set; }

    // "Pozitif" | "Negatif" | "Nötr"
    [JsonPropertyName("impact")]
    public string? Impact { get; set; }

    // 1 short sentence why it matters
    [JsonPropertyName("explanation")]
    public string? Explanation { get; set; }

    // 0-100 (heuristic importance)
    [JsonPropertyName("importance_score")]
    public int Importance_Score { get; set; }

    // "intraday" | "short" | "long"
    [JsonPropertyName("time_horizon")]
    public string? Time_Horizon { get; set; }

    // max 3 short reasons
    [JsonPropertyName("reasons")]
    public List<string>? Reasons { get; set; }
}