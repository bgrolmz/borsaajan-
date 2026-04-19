FROM mcr.microsoft.com/dotnet/aspnet:9.0 AS base
WORKDIR /app
EXPOSE 8080

FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src
COPY ["BorsaAjani_Web/BorsaAjani_Web.csproj", "BorsaAjani_Web/"]
RUN dotnet restore "BorsaAjani_Web/BorsaAjani_Web.csproj"
COPY . .
WORKDIR "/src/BorsaAjani_Web"
RUN dotnet build "BorsaAjani_Web.csproj" -c Release -o /app/build

FROM build AS publish
RUN dotnet publish "BorsaAjani_Web.csproj" -c Release -o /app/publish

FROM base AS final
WORKDIR /app
COPY --from=publish /app/publish .
ENTRYPOINT ["dotnet", "BorsaAjani_Web.dll"]
