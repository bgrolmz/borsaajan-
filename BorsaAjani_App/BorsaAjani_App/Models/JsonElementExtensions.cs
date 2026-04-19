using System.Globalization;
using System.Text.Json;

namespace BorsaAjani_App.Models;

public static class JsonElementExtensions
{
    public static bool IsNullOrUndefined(this JsonElement element)
        => element.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null;

    // Convenience overloads for non-null JsonElement
    public static string? GetStringOrNull(this JsonElement element) => GetStringOrNull((JsonElement?)element);
    public static int? GetIntOrNull(this JsonElement element) => GetIntOrNull((JsonElement?)element);
    public static double? GetDoubleOrNull(this JsonElement element) => GetDoubleOrNull((JsonElement?)element);
    public static IEnumerable<string> GetStringArray(this JsonElement element) => GetStringArray((JsonElement?)element);
    public static IEnumerable<double> GetNumberArray(this JsonElement element) => GetNumberArray((JsonElement?)element);

    public static JsonElement? TryGetProperty(this JsonElement element, string propertyName)
    {
        if (element.ValueKind != JsonValueKind.Object) return null;
        return element.TryGetProperty(propertyName, out var prop) ? prop : null;
    }

    public static string? GetStringOrNull(this JsonElement? element)
    {
        if (element is null) return null;
        var e = element.Value;
        if (e.ValueKind is JsonValueKind.Null or JsonValueKind.Undefined) return null;
        if (e.ValueKind == JsonValueKind.String) return e.GetString();
        return e.ToString();
    }

    public static int? GetIntOrNull(this JsonElement? element)
    {
        if (element is null) return null;
        var e = element.Value;
        if (e.ValueKind is JsonValueKind.Null or JsonValueKind.Undefined) return null;
        if (e.ValueKind == JsonValueKind.Number)
        {
            if (e.TryGetInt32(out var i)) return i;
            if (e.TryGetDouble(out var d)) return (int)d;
        }

        if (e.ValueKind == JsonValueKind.String)
        {
            var s = (e.GetString() ?? "").Trim().Replace("%", "");
            if (int.TryParse(s, NumberStyles.Integer, CultureInfo.InvariantCulture, out var i)) return i;
            if (double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out var d)) return (int)d;
        }

        return null;
    }

    public static double? GetDoubleOrNull(this JsonElement? element)
    {
        if (element is null) return null;
        var e = element.Value;
        if (e.ValueKind is JsonValueKind.Null or JsonValueKind.Undefined) return null;
        if (e.ValueKind == JsonValueKind.Number)
        {
            return e.TryGetDouble(out var d) ? d : null;
        }

        if (e.ValueKind == JsonValueKind.String)
        {
            var s = (e.GetString() ?? "").Trim().Replace("$", "");
            return double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out var d) ? d : null;
        }

        return null;
    }

    public static IEnumerable<string> GetStringArray(this JsonElement? element)
    {
        if (element is null) yield break;
        var e = element.Value;
        if (e.ValueKind != JsonValueKind.Array) yield break;
        foreach (var item in e.EnumerateArray())
        {
            var s = item.ValueKind == JsonValueKind.String ? item.GetString() : item.ToString();
            if (!string.IsNullOrWhiteSpace(s)) yield return s!;
        }
    }

    public static IEnumerable<double> GetNumberArray(this JsonElement? element)
    {
        if (element is null) yield break;
        var e = element.Value;
        if (e.ValueKind != JsonValueKind.Array) yield break;
        foreach (var item in e.EnumerateArray())
        {
            if (item.ValueKind == JsonValueKind.Number && item.TryGetDouble(out var d))
                yield return d;
            else if (item.ValueKind == JsonValueKind.String && double.TryParse(item.GetString(), NumberStyles.Float, CultureInfo.InvariantCulture, out var ds))
                yield return ds;
        }
    }
}
