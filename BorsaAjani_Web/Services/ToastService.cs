namespace BorsaAjani_Web.Services;

public enum ToastLevel { Info, Success, Warning, Error }

public class ToastMessage
{
    public Guid Id { get; init; } = Guid.NewGuid();
    public string Text { get; init; } = "";
    public ToastLevel Level { get; init; } = ToastLevel.Info;
    public int DurationMs { get; init; } = 4000;
}

public class ToastService
{
    private readonly List<ToastMessage> _items = new();
    public IReadOnlyList<ToastMessage> Items => _items;

    public event Action? OnChange;

    public void Show(string text, ToastLevel level = ToastLevel.Info, int durationMs = 4000)
    {
        var msg = new ToastMessage { Text = text, Level = level, DurationMs = durationMs };
        _items.Add(msg);
        OnChange?.Invoke();

        _ = Task.Run(async () =>
        {
            await Task.Delay(durationMs);
            Dismiss(msg.Id);
        });
    }

    public void Info(string text, int ms = 4000) => Show(text, ToastLevel.Info, ms);
    public void Success(string text, int ms = 4000) => Show(text, ToastLevel.Success, ms);
    public void Warning(string text, int ms = 5000) => Show(text, ToastLevel.Warning, ms);
    public void Error(string text, int ms = 6000) => Show(text, ToastLevel.Error, ms);

    public void Dismiss(Guid id)
    {
        var n = _items.RemoveAll(x => x.Id == id);
        if (n > 0) OnChange?.Invoke();
    }
}
