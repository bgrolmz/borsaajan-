using Microsoft.AspNetCore.Components.Web;
using BorsaAjani_Web;
using BorsaAjani_Web.Services;

var builder = WebApplication.CreateBuilder(args);

// ─── Blazor + Circuit stability ───────────────────────────────────────────
builder.Services.AddRazorComponents()
    .AddInteractiveServerComponents(options =>
    {
        // Keep disconnected circuits alive for 3 minutes (user navigate away / tab switch)
        options.DisconnectedCircuitRetentionPeriod = TimeSpan.FromMinutes(3);
        // JS interop timeout — analysis calls can be slow
        options.JSInteropDefaultCallTimeout = TimeSpan.FromSeconds(60);
        // Prevent render buffer overflow on slow clients
        options.MaxBufferedUnacknowledgedRenderBatches = 10;
    });

// ─── SignalR hub options ───────────────────────────────────────────────────
builder.Services.AddSignalR(hub =>
{
    hub.MaximumReceiveMessageSize = 512 * 1024; // 512 KB — large analysis payloads
    hub.HandshakeTimeout           = TimeSpan.FromSeconds(30);
    hub.KeepAliveInterval          = TimeSpan.FromSeconds(15);
    hub.ClientTimeoutInterval      = TimeSpan.FromSeconds(60);
});

// ─── Services ─────────────────────────────────────────────────────────────
builder.Services.AddSingleton<ChatContextService>();
builder.Services.AddScoped<FinansalAjanService>();

var backendUrl    = "https://borsaajan-production.up.railway.app";
var backendApiUrl = Environment.GetEnvironmentVariable("BACKEND_API_URL") ?? backendUrl;
Console.WriteLine($"[Config] Backend API URL: {backendApiUrl}");

builder.Services.AddHttpClient("BackendApi", client =>
{
    client.BaseAddress = new Uri(backendApiUrl);
    client.Timeout     = TimeSpan.FromSeconds(180); // 3 min — AI analysis can be slow
});

// ─── Pipeline ─────────────────────────────────────────────────────────────
var app = builder.Build();

if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Error", createScopeForErrors: true);
    app.UseHsts();
}

app.UseStaticFiles();
app.UseRouting();
app.UseAntiforgery();

app.MapRazorComponents<App>()
    .AddInteractiveServerRenderMode();

app.Run();
