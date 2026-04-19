# UI Overhaul - Code Reference Guide

Quick reference for the new UI components and styling.

---

## 🎨 CSS Classes Reference

### Glassmorphism Cards

```css
.glass-card {
    background: rgba(255, 255, 255, 0.05);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 16px;
}
```

### Watchlist Components

```css
.watchlist-container { }      /* Main wrapper */
.watchlist-grid { }            /* Card grid layout */
.watchlist-item { }            /* Individual stock card */
.watchlist-symbol { }          /* Large bold symbol */
.watchlist-price { }           /* Price display */
.watchlist-ai-badge { }        /* Sentiment badge */
```

### News Feed Components

```css
.news-feed-container { }       /* Main wrapper */
.news-grid { }                 /* Card grid layout */
.news-card { }                 /* Individual news card */
.news-card.high-impact { }     /* High-impact news with glow */
.news-analysis { }             /* "Why This Matters" section */
.news-impact-badge { }         /* HIGH/MEDIUM/LOW badge */
```

### Utility Classes

```css
.fade-in { }                   /* Entry animation */
.slide-in-right { }            /* Slide from right */
.shimmer { }                   /* Loading effect */
.text-gradient { }             /* Gradient text */
```

---

## 📦 Blazor Components

### Watchlist Section (in Portfolio Tab)

```razor
<div class="watchlist-container fade-in">
    <div class="watchlist-header">
        <h2 class="watchlist-title">Özel Takip Listesi</h2>
        <button class="btn-add-watchlist" @onclick="OpenAddWatchlistDialog">
            <span>➕</span>
            <span>Hisse Ekle</span>
        </button>
    </div>
    
    <div class="watchlist-grid">
        @foreach (var item in watchlistItems)
        {
            <div class="watchlist-item slide-in-right">
                <div class="watchlist-symbol">@item.Symbol</div>
                <div class="watchlist-price-row">
                    <span class="watchlist-price">$@item.Price.ToString("F2")</span>
                    <span class="price-change">@item.Change.ToString("F2")%</span>
                </div>
                <div class="watchlist-ai-badge badge-bullish">
                    <span class="icon-rocket"></span>
                    <span>Bullish</span>
                </div>
            </div>
        }
    </div>
</div>
```

### News Feed (in Bildirimler Tab)

```razor
<div class="news-feed-container">
    <div class="news-feed-header">
        <h1 class="news-feed-title">📰 Piyasa Haberleri</h1>
        <p class="news-feed-subtitle">Hermes AI tarafından analiz edilen haberler</p>
    </div>
    
    <div class="news-grid">
        @foreach (var news in newsItems)
        {
            <div class="news-card @(news.Impact == "HIGH" ? "high-impact" : "")">
                <div class="news-header">
                    <span class="news-impact-badge impact-high">HIGH</span>
                    <span class="news-timestamp">@news.TimeAgo</span>
                </div>
                
                <h3 class="news-title">@news.Title</h3>
                
                <div class="news-symbols">
                    @foreach (var symbol in news.Symbols)
                    {
                        <span class="symbol-tag">@symbol</span>
                    }
                </div>
                
                <div class="news-analysis">
                    <div class="news-analysis-label">
                        <span>🤖</span>
                        <span>Why This Matters</span>
                    </div>
                    <p class="news-analysis-text">@news.WhyAnalysis</p>
                </div>
            </div>
        }
    </div>
</div>
```

---

## 🔧 C# Data Models

### WatchlistItem

```csharp
private class WatchlistItem
{
    public string Symbol { get; set; } = "";
    public double Price { get; set; }
    public double Change { get; set; }
    public string Sentiment { get; set; } = "neutral"; // bullish, bearish, neutral
}
```

### NewsItem

```csharp
private class NewsItem
{
    public int Id { get; set; }
    public string Title { get; set; } = "";
    public string Summary { get; set; } = "";
    public string WhyAnalysis { get; set; } = "";
    public string Impact { get; set; } = "LOW"; // HIGH, MEDIUM, LOW
    public string Sentiment { get; set; } = "neutral";
    public List<string> Symbols { get; set; } = new();
    public DateTime Timestamp { get; set; }
    public string TimeAgo
    {
        get
        {
            var diff = DateTime.Now - Timestamp;
            if (diff.TotalMinutes < 60) return $"{(int)diff.TotalMinutes}d önce";
            if (diff.TotalHours < 24) return $"{(int)diff.TotalHours}s önce";
            return $"{(int)diff.TotalDays}g önce";
        }
    }
}
```

---

## 🎯 Key Methods

### Watchlist Methods

```csharp
// Load watchlist data
private async Task LoadWatchlist()
{
    isLoadingWatchlist = true;
    StateHasChanged();
    
    // Load from API or sample data
    watchlistItems = new List<WatchlistItem> { ... };
    
    isLoadingWatchlist = false;
    StateHasChanged();
}

// Add stock to watchlist
private async Task OpenAddWatchlistDialog()
{
    var symbol = await JSRuntime.InvokeAsync<string>("prompt", "Hisse sembolünü girin:");
    if (!string.IsNullOrWhiteSpace(symbol))
    {
        watchlistItems.Add(new WatchlistItem { Symbol = symbol.ToUpper(), ... });
        StateHasChanged();
    }
}

// Remove from watchlist
private void RemoveFromWatchlist(string symbol)
{
    watchlistItems.RemoveAll(x => x.Symbol == symbol);
    StateHasChanged();
}
```

### News Feed Methods

```csharp
// Load news from Hermes API
private async Task LoadNotifications()
{
    isLoadingNotifications = true;
    newsItems.Clear();
    StateHasChanged();
    
    try
    {
        var client = HttpClientFactory.CreateClient("BackendApi");
        var response = await client.GetAsync("/hermes/recent?limit=20");
        
        if (response.IsSuccessStatusCode)
        {
            var newsJson = await response.Content.ReadAsStringAsync();
            var newsData = JsonSerializer.Deserialize<JsonElement>(newsJson);
            
            // Parse news items...
        }
    }
    catch (Exception ex)
    {
        LoadSampleNews(); // Fallback to sample data
    }
    finally
    {
        isLoadingNotifications = false;
        StateHasChanged();
    }
}

// Load sample news data
private void LoadSampleNews()
{
    newsItems = new List<NewsItem>
    {
        new NewsItem
        {
            Title = "Fed Faiz Kararı Beklenenden Hawkish Geldi",
            Impact = "HIGH",
            Sentiment = "bearish",
            Symbols = new List<string> { "SPY", "QQQ", "NVDA" },
            WhyAnalysis = "Yüksek faizler teknoloji hisselerini olumsuz etkiler...",
            Timestamp = DateTime.Now.AddHours(-2)
        },
        // More items...
    };
}
```

---

## 🎨 Color Variables

```css
:root {
    /* Gradients */
    --gradient-primary: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
    
    /* Glassmorphism */
    --glass-bg: rgba(255, 255, 255, 0.05);
    --glass-border: rgba(255, 255, 255, 0.1);
    --glass-hover: rgba(255, 255, 255, 0.08);
    
    /* Accent Colors */
    --accent-cyan: #00d4ff;
    --accent-blue: #0099cc;
    --accent-purple: #7d5fff;
    --accent-green: #00ff88;
    
    /* Status Colors */
    --color-bullish: #3fb950;
    --color-bearish: #f85149;
    --color-neutral: #8b949e;
    --color-high-impact: #ff4757;
    
    /* Text Colors */
    --text-primary: #ffffff;
    --text-secondary: rgba(255, 255, 255, 0.8);
    --text-muted: rgba(255, 255, 255, 0.6);
    
    /* Shadows */
    --shadow-glow: 0 0 20px rgba(0, 212, 255, 0.3);
    --shadow-card: 0 8px 32px rgba(0, 0, 0, 0.4);
    --shadow-elevated: 0 12px 48px rgba(0, 0, 0, 0.6);
}
```

---

## 🎬 Animation Keyframes

### Fade In

```css
@keyframes fade-in {
    from {
        opacity: 0;
        transform: translateY(20px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}
```

### Slide In Right

```css
@keyframes slide-in-right {
    from {
        opacity: 0;
        transform: translateX(30px);
    }
    to {
        opacity: 1;
        transform: translateX(0);
    }
}
```

### Shimmer (Loading)

```css
@keyframes shimmer {
    0% {
        background-position: -200% 0;
    }
    100% {
        background-position: 200% 0;
    }
}
```

### Pulse Glow (High Impact)

```css
@keyframes pulse-glow {
    0%, 100% {
        box-shadow: 0 0 20px rgba(255, 71, 87, 0.3);
    }
    50% {
        box-shadow: 0 0 40px rgba(255, 71, 87, 0.6);
    }
}
```

---

## 🔗 Icon Classes

Quick reference for icon classes (uses CSS `::before` pseudo-elements):

| Class | Icon | Usage |
|-------|------|-------|
| `.icon-trend-up::before` | 📈 | Positive trends |
| `.icon-trend-down::before` | 📉 | Negative trends |
| `.icon-rocket::before` | 🚀 | Bullish sentiment |
| `.icon-warning::before` | ⚠️ | Caution/warnings |
| `.icon-fire::before` | 🔥 | High impact news |
| `.icon-chart::before` | 📊 | Charts/analytics |
| `.icon-bell::before` | 🔔 | Notifications |

---

## 📱 Responsive Breakpoints

```css
@media (max-width: 768px) {
    .watchlist-grid {
        grid-template-columns: 1fr;
    }
    
    .news-grid {
        grid-template-columns: 1fr;
    }
    
    .news-feed-title {
        font-size: 2rem;
    }
}
```

---

## 🚀 Quick Start

### 1. Add CSS to Layout

```razor
<HeadContent>
    <link rel="stylesheet" href="css/app.css" />
</HeadContent>
```

### 2. Use Glassmorphism

```html
<div class="glass-card">
    <!-- Your content -->
</div>
```

### 3. Add Animations

```html
<div class="fade-in">
    <!-- Animated content -->
</div>
```

### 4. Apply Gradients

```html
<h1 class="text-gradient">Gradient Text</h1>
```

---

## 📞 Questions?

Check the main summary: `UI_OVERHAUL_SUMMARY.md`
