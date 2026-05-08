# Railway Volume Setup — KRİTİK

## Sorun
Railway container'ı **ephemeral filesystem** kullanır. Her deploy'da `/app` sıfırlanır. SQLite DB de sıfırlanır.

**Belirtiler:**
- Watchlist'e eklediğin hisseler kayboluyor
- Geçmiş analizler gidiyor
- Hermes haber pipeline boş çalışıyor (watchlist boş olduğu için)
- Paper trading geçmişi sıfırlanıyor

## Çözüm — Volume Mount

### Railway Dashboard adımları

1. **Railway Dashboard** → backend servisi seç (BorsaAjan_Backend)
2. Üst menüden **Settings** → **Volumes** sekmesi
3. **+ New Volume** tıkla
4. Ayarlar:
   - **Mount path:** `/app/data`
   - **Volume name:** `borsa-data` (veya istediğin)
5. **Create** tıkla
6. Servisi otomatik redeploy edecek

### Doğrulama

Deploy logs'ta şunu görmeli:
```
[DB] init_db() | path=/app/data/borsa.db | source=default(<repo_root>/data/borsa.db) | exists=True | size_kb=X.X
```

İlk deploy'dan sonra:
- Watchlist'e hisse ekle
- Servisi redeploy et
- Sayfayı yenile → hisse hala duruyor olmalı

### Backup

Volume otomatik backup yapmaz. `data/backups/` klasörüne günlük backup APScheduler tarafından alınıyor. Aynı volume'da kaldığı için kalıcı.

İstersen Railway'in **Snapshots** özelliğini etkinleştir (Pro plan).

## Env vars (opsiyonel)

Volume olmadan da çalışan alternatif: external DB veya farklı path:

```
BORSA_DB_PATH=/app/data/borsa.db
```

Bu zaten default — volume mount yeterli.
