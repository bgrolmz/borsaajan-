FROM mcr.microsoft.com/dotnet/aspnet:9.0 AS base
WORKDIR /app
EXPOSE 8080

FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src
COPY ["BorsaAjani_Web.csproj", "./"]
RUN dotnet restore "BorsaAjani_Web.csproj"
COPY . .
RUN dotnet build "BorsaAjani_Web.csproj" -c Release -o /app/build

FROM build AS publish
RUN dotnet publish "BorsaAjani_Web.csproj" -c Release -o /app/publish

FROM base AS final
WORKDIR /app
COPY --from=publish /app/publish .
ENV ASPNETCORE_URLS=http://+:8080
ENTRYPOINT ["dotnet", "BorsaAjani_Web.dll"]
