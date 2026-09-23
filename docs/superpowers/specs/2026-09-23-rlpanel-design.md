# rlpanel — Yerel RL Eğitim Paneli — Tasarım

Tarih: 2026-09-23 · Durum: onay bekliyor

## 1. Amaç

RL eğitimlerinin çıktısını terminal yerine yerel bir web panelinde görmek.

- **Genel**: birden çok RL projesinde (DroneTrackingRL, LunarRocket, …) kullanılacak.
- **Canlı**: eğitim sürerken grafikler ve loglar anlık güncellenir.
- **Geriye dönük**: bitmiş eğitimlerin log dosyaları panele yüklenebilir.
- **Taşınabilir**: proje başka PC'ye taşınıp `pip install -e .` yapıldığında panel de kurulur;
  eğitim başladığında panel kendiliğinden açılır.
- **İndirilebilir**: her grafik PNG/SVG/CSV, tüm run tek zip olarak indirilebilir.

**Başarı ölçütü**: DroneTrackingRL'de bir PPO eğitimi başlatıldığında, eğitim koduna 1–2 satır
eklenmiş olması dışında hiçbir ek adım olmadan tarayıcıda panel açılır; ilerleme %, anlık reward,
reward/episode/learning-rate/success-rate grafikleri ve terminal logu canlı görünür; eğitim
bitince tüm grafikler indirilebilir.

## 2. Mimari kararlar

| Karar | Seçim | Gerekçe |
|---|---|---|
| Dağıtım | Ayrı pip paketi `rlpanel`, ayrı git reposu (`D:\Projects\rlpanel`), projeler `rlpanel @ git+https://github.com/...` ile bağımlı | Tek kaynak kod, tüm projeler güncellemeden faydalanır; internet her zaman var (kullanıcı teyidi) |
| Backend | Python, FastAPI + uvicorn, WebSocket ile canlı yayın | RL projeleri zaten Python; ek çalışma zamanı gerekmez |
| Depolama | SQLite, tek dosya `~/.rlpanel/panel.db` (WAL modu) | Çökmeye dayanıklı, kurulum gerektirmez |
| Frontend | Paket içinde hazır statik dosyalar (build adımı yok), grafikler uPlot ile | Diğer PC'de Node/npm gerekmez; uPlot 100k+ noktada akıcı |
| Varsayılan port | 8765 (meşgulse ve rlpanel değilse sıradaki port) | |

## 3. Paket yapısı

```
rlpanel/
  pyproject.toml
  src/rlpanel/
    __init__.py      → Panel, PanelCallback dışa açılır
    client.py        → Panel: run başlat, metrik/log/config/sonuç gönder, arka plan gönderim thread'i
    sb3.py           → PanelCallback: SB3 logger'ını yakalar, ilerleme/toplam adım bildirir
    launcher.py      → sunucu çalışıyor mu (/api/health)? değilse ayrı süreçte başlat + tarayıcı aç
    logcapture.py    → logging handler + stdout/stderr tee → Konsol
    cli.py           → `rlpanel serve [--port] [--host]`, `rlpanel watch <klasör>`, `rlpanel import <dosya>`
    server/
      app.py         → FastAPI: REST + WebSocket, statik dosya servisi
      store.py       → SQLite erişim katmanı
      watcher.py     → klasör izleme (progress.csv, tfevents, json)
      importers.py   → csv / tfevents / json / zip / buffer.jsonl → run
      export.py      → run zip'i (metrik CSV + config + log)
    web/             → index.html, app.js, styles.css, vendor/uplot.*
  tests/
```

Her birim tek sorumluluklu: `store` HTTP bilmez, `importers` veritabanı bilmez (ortak ara biçime
çevirir), `client` sunucu iç yapısını bilmez (yalnız HTTP API).

## 4. Veri modeli (SQLite)

- **project**(id, name UNIQUE, created_at)
- **run**(id, project_id, name, seed, status ∈ {running, finished, crashed, stopped, unresponsive},
  source ∈ {client, watch, upload}, host, config JSON, results JSON, total_steps, current_step,
  started_at, ended_at, last_heartbeat, content_hash)
- **metric**(run_id, key, step, value, wall_time) — indeks (run_id, key, step)
- **log**(run_id, wall_time, level, line)

Metrik anahtarları serbesttir (`rollout/ep_rew_mean`, `visible_rate`, …); şema önceden tanımlanmaz.

## 5. Veri akışı

### 5.1 İstemci (canlı)
```python
from rlpanel import Panel, PanelCallback
panel = Panel(project="DroneTrackingRL", run=f"seed{seed}", config=cfg)   # server= opsiyonel
model.learn(total_timesteps=N, callback=PanelCallback(panel))
panel.log({"visible_rate": 0.81}, step=t)   # özel metrik
panel.result({"oracle": ..., "fixed": ...}) # özet sonuçlar
panel.finish()                               # çoğu durumda otomatik (atexit / callback sonu)
```
1. `Panel(...)` → launcher sunucuyu kontrol eder; yoksa ayrı süreçte başlatır ve tarayıcıyı run
   sayfasında açar. Varsa yalnız bağlanır (aynı anda birden çok eğitim aynı panelde görünür).
2. Metrik/log kuyruğa girer; arka plan thread'i ~1 sn'de bir toplu `POST /api/runs/{id}/batch`.
3. Sunucu SQLite'a yazar ve WebSocket ile ilgili sayfalara yayar.
4. Heartbeat her gönderimde güncellenir; 30 sn sessiz kalan `running` run → `unresponsive`.
5. Uzak makine: `Panel(server="http://<ip>:8765")` veya `RLPANEL_SERVER` ortam değişkeni.
   Uzaktan erişim için sunucu `rlpanel serve --host 0.0.0.0` ile açılır.

`PanelCallback` toplar: SB3 logger'ının dump ettiği tüm anahtarlar, `num_timesteps`,
`total_timesteps` (ilerleme %/ETA için), learning rate, `rollout/success_rate` (varsa).
Ayrıca `logcapture` ile `logging` kayıtları ve stdout/stderr Konsol'a akar.

### 5.2 Klasör izleme
`rlpanel watch <klasör>` (veya arayüzden klasör ekle): `progress.csv`, `events.out.tfevents.*` (tbparse/tensorboard opsiyonel bağımlılık: `pip install rlpanel[tb]`),
`results.json` dosyalarını izler; yeni satırları artımlı okur. Klasör yolu → proje/run adı
(`<proje>/<run>` son iki parça). Kaynak `watch`.

### 5.3 Yükleme
Arayüzde sürükle-bırak: `progress.csv`, tfevents, `results.json`, `.rlpanel_buffer.jsonl` veya
bunları içeren `.zip`. Proje/run adı sorulur (dosya yolundan önerilir). İçerik hash'i aynı olan
yükleme reddedilir ("zaten var"). Kaynak `upload`.

## 6. Arayüz

### 6.1 Ana sayfa
- Projeye göre gruplu run kartları: durum rozeti, ilerleme çubuğu, son reward, reward sparkline.
- Filtre: proje, durum, tarih, makine.
- "Log yükle" (sürükle-bırak) ve "Klasör izle".
- Çoklu seçim → **Karşılaştır**: seçilen run'ların aynı metrikleri üst üste çizilir.

### 6.2 Run detayı
**Üst şerit (canlı)**: ilerleme % + çubuk + `adım / toplam` + ETA + FPS · anlık reward · en iyi
reward · son episode uzunluğu · başarı oranı (varsa) · learning rate · geçen süre · makine · durum.

**Grafikler**: loglanan **her metrik** için otomatik grafik. "Temel" grubu en üstte: reward
(`ep_rew_mean`), episode uzunluğu, başarı oranı, learning rate. Kalanlar önek grubuyla
(`rollout/`, `train/`, `eval/`, önek yoksa "Özel"). Kontroller: x ekseni adım/zaman, yumuşatma
kaydırıcısı, log ölçek, hover'da değer.

**Sekmeler**: Grafikler · Konsol (canlı, seviye filtresi, arama) · Config (tablo) · Sonuçlar
(`results` JSON tablo halinde).

### 6.3 İndirme
- Her grafik: PNG (2× çözünürlük), SVG, CSV (grafiğin verisi).
- Run: "Tümünü indir" → zip (tüm grafik PNG'leri + `metrics.csv` + `config.json` + `results.json`
  + `console.log`). PNG'ler tarayıcıda üretilip zip'e eklenir.
- Karşılaştırma grafikleri de aynı şekilde indirilebilir.

### 6.3a Canlı run'ı önceki eğitimlerle karşılaştırma
- Run detayında **"Önceki eğitimlerle karşılaştır"** seçicisi: aynı projeden (varsayılan) veya
  herhangi bir projeden bitmiş run'lar seçilir; seçilenler her grafiğe **referans çizgisi** olarak
  (soluk renk, canlı run vurgulu) üst üste çizilir. Canlı run güncellendikçe grafikler de güncellenir.
- Hızlı seçimler: "aynı projenin son run'ı", "aynı projenin en iyi run'ı" (son `ep_rew_mean`'e göre),
  "aynı config adı / seed grubu".
- Birden çok seed'li gruplar için isteğe bağlı **ortalama ± std bandı** olarak gösterim.
- Üst şeritte **aynı adımda fark**: canlı run'ın şu anki reward'ı, referans run'ın aynı adımdaki
  değeriyle karşılaştırılır (ör. `+12.4 / %8 önde`). Referans o adıma hiç ulaşmadıysa gösterilmez.
- Seçim run başına URL'de tutulur (`?ref=12,15`), sayfa yenilenince kaybolmaz.

### 6.4 Görünüm
Koyu/açık tema. Görsel tasarım uygulama aşamasında UI skill'i (frontend-design / ui-ux-pro-max)
ile yapılır.

## 7. Hata durumları

Kural: **panel yüzünden eğitim asla çökmez veya yavaşlamaz.**

| Durum | Davranış |
|---|---|
| Sunucu yok / kapandı | İstemci `<run_dir>/.rlpanel_buffer.jsonl`'a yazar; sunucu dönünce otomatik gönderir; olmazsa dosya yüklenebilir |
| İstemci içi hata | Yakalanır, tek satır uyarı, eğitim devam eder; gönderim ayrı thread'de |
| Port meşgul | `/api/health` ile rlpanel mi kontrol edilir; değilse sıradaki port |
| Eğitim istisnası | Traceback Konsol'a, run `crashed`; Ctrl+C → `stopped` |
| Bozuk yükleme | Okunamayan satırlar raporlanır, geri kalanı içe alınır |
| Aynı dosya iki kez | Hash eşleşirse "zaten var" |
| 30 sn heartbeat yok | `unresponsive`; veri gelirse tekrar `running` |

## 8. Test

- **pytest**: store; importers (csv/tfevents/json/zip/buffer); watcher (artımlı okuma);
  client buffer (sunucu kapalıyken yazma + sonra gönderme); launcher (port/health);
  PanelCallback ile gerçek küçük SB3 PPO CartPole eğitimi → metrikler ve ilerleme DB'de.
- **Playwright duman testi**: ana sayfa açılır, canlı veri grafiğe düşer, PNG/CSV/zip iner.

## 9. İlk entegrasyon: DroneTrackingRL

- `pyproject.toml`'a `rlpanel` bağımlılığı.
- `real_data/experiment.py`: `model.learn(...)`'a `PanelCallback`; proje adı, seed, config
  otomatik; `dronetrackingrl.*` logger'ları Konsol'a; encoder kaybı, `visible_rate`, kamera
  payları özel metrik; `results` → `panel.result(...)`.
- Mevcut `progress.csv` / `results.json` çıktıları **aynen kalır**.

## 10. Kapsam dışı (şimdilik)

Kimlik doğrulama (yalnız yerel ağ), panelden eğitim başlatma/durdurma, video/görsel loglama.
İleride eklenebilir.
