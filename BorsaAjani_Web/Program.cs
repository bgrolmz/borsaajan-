using Microsoft.AspNetCore.Components.Web;
using BorsaAjani_Web;
using BorsaAjani_Web.Services;

var builder = WebApplication.CreateBuilder(args);

// Add services to the container.
builder.Services.AddRazorComponents()
    .AddInteractiveServerComponents();

// Add ChatContextService as singleton
builder.Services.AddSingleton<ChatContextService>();

// Configure HttpClient for backend API
// Use BACKEND_API_URL environment variable if set, otherwise default to localhost
var backendApiUrl = Environment.GetEnvironmentVariable("BACKEND_API_URL") ?? "https://borsaajan-production.up.railway.app";
Console.WriteLine($"[Config] Backend API URL: {backendApiUrl}");

builder.Services.AddHttpClient("BackendApi", client =>
{
    client.BaseAddress = new Uri(backendApiUrl);
    client.Timeout = TimeSpan.FromSeconds(300);
});

var app = builder.Build();

// Configure the HTTP request pipeline.
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
