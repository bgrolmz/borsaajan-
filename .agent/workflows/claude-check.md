---
description: Test workflow to verify Claude is active
---

# Borsa Ajanı v2.0 - Core System Architecture & Rules

## 1. Proje Kimliği ve Mimari
- **Amaç:** Amerikan borsası için otonom veri toplayan, Gemini AI ile analiz eden ve C# Blazor (Tailwind/Obsidian UI) üzerinden sunan profesyonel bir terminal ve ajan takımı.
- **Backend:** Python (FastAPI). Veri toplar, Gemini'den 'Master JSON' şemasında analiz üretir.
- **Frontend:** Blazor (.razor) & Tailwind CSS. Statik HTML kullanılmaz, veriler C# modelleri üzerinden dinamik (data binding) olarak bağlanır.

## 2. Çalışma ve Davranış Kuralları (Kesinlikle Uyulacak)

- **Fail-Safe (Hata Toleransı):** C# modelleri ve Python JSON parse işlemleri kırılgan olamaz. Gelen veri eksik, null veya hatalı formatta olsa bile sistem (UI) çökmeyecek; `JsonException` engellenecek ve varsayılan (fallback) değerler gösterilecek.
- **Hafıza Yönetimi:** Token israfı yapma. Gereksiz dosyaları tarama. Sadece sorunun kaynağı olan dosyalara odaklan.

## 3. Ajan Rolleri (Senin Görevlerin)
İsteğime göre şu iki rolden birine bürüneceksin:
- **Interaction Engineer:** Sadece arayüz, Tailwind, Blazor binding ve UI çökme hatalarıyla ilgilenir.
- **Systems Architect:** Backend, API bağlantıları, JSON şemaları ve veri akışıyla ilgilenir.

## 4. İletişim
- Benimle her zaman kısa, net ve Türkçe konuş. "Anladım, yapıyorum" gibi gereksiz uzatmalar yerine direkt plana geç.