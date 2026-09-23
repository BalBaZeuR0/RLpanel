# rlpanel — yerel, canlı RL eğitim paneli

RL eğitimlerinin çıktısını terminal yerine tarayıcıda gör: ilerleme %, anlık reward, reward / episode /
learning rate / başarı oranı ve loglanan **her** metriğin grafiği, canlı konsol. Bitmiş eğitimleri yükle,
önceki eğitimlerle karşılaştır, her grafiği PNG / SVG / CSV indir.

## Kurulum (projene bağımlılık olarak)

`pyproject.toml`:
```toml
dependencies = ["rlpanel[sb3] @ git+https://github.com/BalBaZeuR0/RLpanel"]
```
Sonra `pip install -e .`. Proje başka bilgisayara taşındığında panel de onunla gelir.

## Kullanım

```python
from rlpanel import Panel, PanelCallback

panel = Panel(project="Projem", run="seed0", config=cfg)      # panel yoksa açar, tarayıcıyı açar
model.learn(total_timesteps=100_000, callback=PanelCallback(panel))
panel.log({"eval/basari": 0.93}, step=model.num_timesteps)    # kendi metriğin
panel.result({"final": 0.93})                                 # Sonuçlar sekmesi
panel.finish()
```
Tek satırlık kısa yol: `model.learn(..., callback=PanelCallback(project="Projem", run="seed0"))`.

- SB3 kullanmıyorsan: `panel.log({...}, step=t)`, `panel.progress(t, toplam)`.
- `print` ve `logging` çıktıları Konsol sekmesine akar.
- Hata olursa run **Çöktü**, Ctrl+C'de **Durduruldu** olur. 30 sn ses gelmezse **Yanıt vermiyor** olarak işaretlenir.
- Sunucu kapalıysa veriler `.rlpanel/<proje>-<run>/.rlpanel_buffer.jsonl` dosyasında birikir. Sunucu açılınca otomatik gönderilir; istersen bu dosyayı elle de yükleyebilirsin.

## Komutlar

| Komut | Ne yapar |
|---|---|
| `rlpanel serve` | Paneli açar (http://127.0.0.1:8765) |
| `rlpanel serve --host 0.0.0.0` | Uzak makinelerden erişilebilir yapar |
| `rlpanel watch <klasör>` | SB3 `progress.csv` / tfevents / `results.json` dosyalarını canlı izler |
| `rlpanel import <dosya> --project P --run r` | Bitmiş eğitimin logunu yükler |

## Ortam değişkenleri

| Değişken | Etki |
|---|---|
| `RLPANEL_SERVER=http://ip:8765` | Başka makinedeki panele gönder |
| `RLPANEL_NO_BROWSER=1` | Tarayıcı açma |
| `RLPANEL_DISABLE=1` | Paneli tamamen kapat (testler, CI) |
| `RLPANEL_HOME` / `RLPANEL_DB` | Veri klasörü / veritabanı yolu (varsayılan `~/.rlpanel/panel.db`) |

## Geliştirme

```powershell
python -m venv .venv; .venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\python -m pytest -q
```
