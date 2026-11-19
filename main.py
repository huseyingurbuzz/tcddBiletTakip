from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
import argparse
import os
import time
import re
import json
from datetime import datetime


def _validate_config(cfg):
    required = ["NEREDEN", "NEREYE", "TARIH", "SAAT_BASLANGIC", "SAAT_BITIS", "MIN_KOLTUK"]
    for key in required:
        if key not in cfg or str(cfg[key]).strip() == "":
            raise ValueError(f"{key} bilgisi eksik!")
    return {
        "NEREDEN": str(cfg["NEREDEN"]).strip(),
        "NEREYE": str(cfg["NEREYE"]).strip(),
        "TARIH": str(cfg["TARIH"]).strip(),
        "SAAT_BASLANGIC": str(cfg["SAAT_BASLANGIC"]).strip(),
        "SAAT_BITIS": str(cfg["SAAT_BITIS"]).strip(),
        "MIN_KOLTUK": int(cfg["MIN_KOLTUK"]),
    }


def arama_konfigurasyonlarini_oku():
    try:
        env_json = os.getenv("DEPARTURE_INFO_JSON", "").strip()
        if env_json:
            data = json.loads(env_json)
            searches = data.get("searches", []) if isinstance(data, dict) else data
            if not isinstance(searches, list) or not searches:
                raise ValueError("DEPARTURE_INFO_JSON içinde dolu bir arama listesi olmalı.")
            return [_validate_config(cfg) for cfg in searches]

        if os.path.exists("departureInfo.json"):
            with open("departureInfo.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            searches = data.get("searches", []) if isinstance(data, dict) else data
            if not isinstance(searches, list) or not searches:
                raise ValueError("departureInfo.json içinde dolu bir arama listesi olmalı.")
            return [_validate_config(cfg) for cfg in searches]

        legacy = {}
        with open("departureInfo.txt", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    legacy[key.strip()] = value.strip()
        cfg = {
            "NEREDEN": legacy.get("NEREDEN", ""),
            "NEREYE": legacy.get("NEREYE", ""),
            "TARIH": legacy.get("TARIH", ""),
            "SAAT_BASLANGIC": legacy.get("SAAT BASLANGIC", ""),
            "SAAT_BITIS": legacy.get("SAAT BITIS", ""),
            "MIN_KOLTUK": int(legacy.get("KOLTUK SAYISI>", "0") or "0"),
        }
        return [_validate_config(cfg)]
    except Exception as e:
        print(f"Konfigürasyon okuma hatası: {e}")
        return []


class TCDDBiletKontrol:
    CHROMIUM_PATH = os.environ.get("CHROMIUM_PATH", "/Applications/Chromium.app/Contents/MacOS/Chromium")
    CHROMEDRIVER_PATH = os.environ.get(
        "CHROMEDRIVER_PATH", os.path.join(os.path.dirname(__file__), "chromedriver")
    )

    def __init__(self):
        self.service = Service(self.CHROMEDRIVER_PATH)
        self.options = webdriver.ChromeOptions()
        self.options.binary_location = self.CHROMIUM_PATH
        for arg in (
            '--headless=new'
            '--disable-software-rasterizer', '--disable-features=BackForwardCache',
            '--disable-background-networking', '--disable-background-timer-throttling',
            '--disable-renderer-backgrounding', '--disable-features=Translate,MediaRouter',
            '--blink-settings=imagesEnabled=false', '--disk-cache-size=1',
            '--disable-features=PaintHolding',
            '--disable-site-isolation-trials',
            '--window-size=1280,720', '--disable-gpu', '--enable-javascript',
            '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
            '--disable-dev-tools', '--disable-extensions',
            '--user-data-dir=/tmp/chrome-user-data', '--data-path=/tmp/chrome-data',
            '--disk-cache-dir=/tmp/chrome-cache',
            '--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        ):
            self.options.add_argument(arg)
        self.driver = None

    def tarayici_baslat(self):
        import shutil
        for item in ('/tmp/chrome-user-data', '/tmp/chrome-data', '/tmp/chrome-cache'):
            if os.path.exists(item):
                shutil.rmtree(item, ignore_errors=True)
        self.driver = webdriver.Chrome(service=self.service, options=self.options)
        self.sayfayi_sifirla()

    def sayfayi_sifirla(self, max_retries=2):
        son_hata = None
        for deneme in range(1, max_retries + 1):
            try:
                self.driver.set_page_load_timeout(30)
                self.driver.get("https://ebilet.tcddtasimacilik.gov.tr/view/eybis/tnmGenel/tcddWebContent.jsf")
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.ID, "fromTrainInput"))
                )
                return
            except Exception as e:
                son_hata = e
                print(f"Sayfa yüklenemedi ({deneme}/{max_retries}): {e}")
                if "tab crashed" in str(e).lower():
                    try:
                        self.driver.quit()
                    except Exception:
                        pass
                    self.driver = webdriver.Chrome(service=self.service, options=self.options)
                if deneme < max_retries:
                    time.sleep(3 * (2 ** (deneme - 1)))
        raise son_hata

    def istasyon_sec(self, input_id, istasyon_adi):
        from selenium.common.exceptions import TimeoutException
        son_hata = None
        aranan = istasyon_adi.split(" (")[0].strip()
        for deneme in range(1, 4):
            try:
                try:
                    WebDriverWait(self.driver, 15).until(
                        EC.invisibility_of_element_located((By.CSS_SELECTOR, ".vld-background"))
                    )
                except TimeoutException:
                    print("Yükleme katmanı hâlâ görünüyor.")
                alan = WebDriverWait(self.driver, 20).until(
                    EC.presence_of_element_located((By.ID, input_id))
                )
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", alan)
                WebDriverWait(self.driver, 10).until(lambda d: alan.is_displayed() and alan.is_enabled())
                self.driver.execute_script("arguments[0].focus();", alan)
                WebDriverWait(self.driver, 30).until(
                    EC.invisibility_of_element_located((By.CSS_SELECTOR, ".vld-background"))
                )
                self.driver.execute_script("""
                    const input = arguments[0];
                    input.focus();
                    input.value = '';
                    input.dispatchEvent(new Event('input', {bubbles: true}));
                """, alan)
                alan.send_keys(aranan)

                def uygun_istasyon(driver):
                    secenekler = driver.find_elements(By.CSS_SELECTOR, "button.dropdown-item.station")
                    for secenek in secenekler:
                        if secenek.is_displayed() and aranan.casefold() in secenek.text.strip().casefold():
                            return secenek
                    return False

                secenek = WebDriverWait(self.driver, 15).until(uygun_istasyon)
                self.driver.execute_script("arguments[0].click();", secenek)
                print(f"İstasyon seçildi: {istasyon_adi}")
                return True
            except Exception as e:
                son_hata = e
                print(f"İstasyon seçimi {deneme}/3 başarısız ({type(e).__name__}): {e}")
                time.sleep(2)
        raise RuntimeError(f"İstasyon seçilemedi: {istasyon_adi}") from son_hata

    def sefer_bilgilerini_al(self):
        try:
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "time[title^='Gidiş'], time[title^='Gidis']")
                )
            )
            time.sleep(3)
            allowed_types = {"BUSINESS", "LOCA", "EKONOMI"}
            journey_leg_koltuk = {}
            journey_leg_saat = {}
            journey_eligible_legs = {}
            journey_all_legs = {}
            segment_to_journey = {}
            current_journey_slot = 0
            vagon_butonlari = self.driver.find_elements(By.CSS_SELECTOR, "button[id*='-vagonType-']")
            for buton in vagon_butonlari:
                buton_text = (buton.get_attribute("innerText") or "").strip()
                button_id = (buton.get_attribute("id") or "").strip()
                id_match = re.match(r"^(.*)-vagonType-\d+-(\d+)-departure$", button_id)
                if id_match:
                    trip_id = id_match.group(1)
                    leg_index = id_match.group(2)
                    segment_id = f"{trip_id}:{leg_index}"
                else:
                    leg_index = "0"
                    segment_id = button_id.split("-vagonType-")[0] if "-vagonType-" in button_id else button_id
                if not segment_id:
                    continue
                if segment_id not in segment_to_journey:
                    if leg_index == "0":
                        current_journey_slot += 1
                    elif current_journey_slot == 0:
                        current_journey_slot = 1
                    segment_to_journey[segment_id] = f"journey-{current_journey_slot}"
                journey_key = segment_to_journey[segment_id]
                journey_all_legs.setdefault(journey_key, set()).add(leg_index)
                tip_normalized = (buton_text.upper().replace("İ", "I").replace("Ş", "S")
                                  .replace("Ğ", "G").replace("Ü", "U")
                                  .replace("Ö", "O").replace("Ç", "C"))
                if not any(allowed in tip_normalized for allowed in allowed_types):
                    continue
                koltuk_eslesme = re.search(r"\((\d+)\)", buton_text)
                koltuk_sayisi = int(koltuk_eslesme.group(1)) if koltuk_eslesme else 0
                if koltuk_sayisi <= 0 or not button_id:
                    continue
                saat_text = self.driver.execute_script("""
                    let el = arguments[0];
                    for (let i = 0; i < 12 && el; i++, el = el.parentElement) {
                        const tm = el.querySelector("time[title^='Gidiş'], time[title^='Gidis']");
                        if (tm) return tm.textContent.trim();
                    }
                    return "";
                """, buton)
                match = re.search(r"\d{2}:\d{2}", saat_text or "")
                if not match:
                    continue
                saat = match.group(0)
                key = (journey_key, leg_index)
                journey_leg_koltuk[key] = journey_leg_koltuk.get(key, 0) + koltuk_sayisi
                journey_leg_saat[key] = saat
                journey_eligible_legs.setdefault(journey_key, set()).add(leg_index)
            sefer_bilgileri = [
                {
                    "saat": min((journey_leg_saat[(journey_key, leg)] for leg in eligible_legs),
                                key=lambda h: datetime.strptime(h, "%H:%M")),
                    "bos_koltuk": str(min(journey_leg_koltuk[(journey_key, leg)] for leg in all_legs)),
                    "segment_saatleri": " -> ".join(sorted(
                        (journey_leg_saat[(journey_key, leg)] for leg in eligible_legs),
                        key=lambda h: datetime.strptime(h, "%H:%M")
                    )),
                    "segment_sayisi": len(all_legs),
                }
                for journey_key, all_legs in journey_all_legs.items()
                for eligible_legs in [journey_eligible_legs.get(journey_key, set())]
                if all_legs and all_legs.issubset(eligible_legs)
            ]
            return sorted(sefer_bilgileri, key=lambda s: datetime.strptime(s["saat"], "%H:%M"))
        except Exception as e:
            print(f"Sefer bilgileri alınırken hata oluştu: {e}")
            return []

    def tarih_sec(self, tarih):
        try:
            gun_str, ay_str, yil_str = tarih.split(".")
            hedef_gun, hedef_ay, hedef_yil = int(gun_str), int(ay_str), int(yil_str)
            tarih_div = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".datePickerInput.departureDate"))
            )
            self.driver.execute_script("arguments[0].click();", tarih_div)
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".daterangepicker td"))
            )
            ay_haritasi = {
                "ocak": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6,
                "temmuz": 7, "agustos": 8, "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12
            }
            for hucre in self.driver.find_elements(By.CSS_SELECTOR, ".daterangepicker td"):
                try:
                    hucre_class = hucre.get_attribute("class") or ""
                    if hucre.text.strip() != str(hedef_gun) or "disabled" in hucre_class or "off" in hucre_class:
                        continue
                    parent_table = hucre.find_element(By.XPATH, "./ancestor::table[1]")
                    ay_baslik = parent_table.find_element(
                        By.XPATH, "./thead//th[@class='month' or contains(@class,'month')]"
                    ).text.strip()
                    ay_baslik_norm = (ay_baslik.lower().replace("ç", "c").replace("ğ", "g")
                                      .replace("ı", "i").replace("ö", "o")
                                      .replace("ş", "s").replace("ü", "u"))
                    parcalar = ay_baslik_norm.split()
                    if len(parcalar) < 2:
                        continue
                    gorunen_ay = ay_haritasi.get(parcalar[0])
                    gorunen_yil = int(parcalar[1]) if parcalar[1].isdigit() else None
                    if gorunen_ay == hedef_ay and gorunen_yil == hedef_yil:
                        self.driver.execute_script("arguments[0].click();", hucre)
                        return True
                except Exception as e:
                    print(f"Tarih hücresi kontrolünde hata: {e}")
            raise RuntimeError(f"{tarih} tarihi seçilemedi!")
        except Exception as e:
            print(f"Tarih seçiminde hata: {e}")
            return False

    def bilet_kontrol(self):
        print("Bu metod artık bilet_kontrol_kombinasyon ile kullanılmalı.")
        return None

    def _sefer_sonuclarini_bekle(self, timeout=25):
        """Sonuçları bekle; güvenlik engelini sonuç yok diye yorumlama."""
        end_time = time.monotonic() + timeout
        last_body = ""
        while time.monotonic() < end_time:
            body = self.driver.find_element(By.TAG_NAME, "body").text
            last_body = body
            normalized = body.casefold()
            if ("güvenlik doğrulaması" in normalized
                    or "doğrulamayı tamamlayın" in normalized
                    or "security verification" in normalized):
                print("TANI URL:", self.driver.current_url, flush=True)
                print("TANI BASLIK:", self.driver.title, flush=True)
                print("TANI SAYFA METNI:", body[:1200], flush=True)
                raise RuntimeError(
                    "TCDD güvenlik doğrulaması istiyor. "
                    "Railway oturumu sonuçları okuyamıyor; koltuk durumu bilinmiyor."
                )
            bulunan = self.driver.find_elements(
                By.CSS_SELECTOR, "time[title^='Gidiş'], time[title^='Gidis']"
            )
            if bulunan:
                print(f"Sefer elemanları bulundu: {len(bulunan)}", flush=True)
                return True
            time.sleep(0.5)
        print("TANI URL:", self.driver.current_url, flush=True)
        print("TANI BASLIK:", self.driver.title, flush=True)
        print("TANI SAYFA METNI:", last_body[:1200], flush=True)
        return False

    def seferleri_filtrele(self, sefer_bilgileri, saat_baslangic, saat_bitis, min_koltuk):
        bas = datetime.strptime(saat_baslangic, "%H:%M").time()
        bit = datetime.strptime(saat_bitis, "%H:%M").time()
        sonuc = []
        for sefer in sefer_bilgileri:
            try:
                saat = datetime.strptime(sefer["saat"], "%H:%M").time()
                koltuk = int(sefer["bos_koltuk"])
            except (ValueError, KeyError, TypeError):
                continue
            if bas <= saat <= bit and koltuk >= int(min_koltuk):
                sonuc.append(sefer)
        return sonuc

    def bilet_kontrol_kombinasyon(self, bilgiler):
        try:
            nereden = bilgiler["NEREDEN"]
            nereye = bilgiler["NEREYE"]
            tarih = bilgiler["TARIH"]
            saat_baslangic = bilgiler["SAAT_BASLANGIC"]
            saat_bitis = bilgiler["SAAT_BITIS"]
            min_koltuk = bilgiler["MIN_KOLTUK"]
            sefer_bulundu = False
            for deneme in range(1, 3):
                if deneme > 1:
                    self.sayfayi_sifirla()
                self.istasyon_sec("fromTrainInput", nereden)
                self.istasyon_sec("toTrainInput", nereye)
                if not self.tarih_sec(tarih):
                    return {"status": "error", "reason": "date_not_selected"}
                sefer_ara_button = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "searchSeferButton"))
                )
                self.driver.execute_script("arguments[0].click();", sefer_ara_button)
                if self._sefer_sonuclarini_bekle(timeout=25):
                    sefer_bulundu = True
                    break
                print(f"Sefer sonuçları yüklenmedi ({deneme}/2): {nereden} - {nereye} | {tarih}")
            if not sefer_bulundu:
                return {"status": "error", "reason": "results_not_loaded"}
            sefer_bilgileri = self.sefer_bilgilerini_al()
            uygun_seferler = self.seferleri_filtrele(
                sefer_bilgileri, saat_baslangic, saat_bitis, min_koltuk
            )
            if uygun_seferler:
                return {
                    "status": "found", "sefer_bilgileri": sefer_bilgileri,
                    "uygun_seferler": uygun_seferler, "nereden": nereden,
                    "nereye": nereye, "tarih": tarih,
                    "saat_baslangic": saat_baslangic, "saat_bitis": saat_bitis,
                    "min_koltuk": min_koltuk,
                }
            print(f"Koltuk yok! {nereden} - {nereye} | {tarih} ({saat_baslangic}-{saat_bitis}, >={min_koltuk})")
            return {"status": "no_seat"}
        except Exception as e:
            print(f"Bir hata oluştu ({type(e).__name__}): {e}")
            return {"status": "error", "reason": str(e)}

    def kapat(self):
        if self.driver:
            self.driver.quit()


def run_checks(kombinasyonlar=None, send_notification=True):
    if kombinasyonlar is None:
        kombinasyonlar = arama_konfigurasyonlarini_oku()
    else:
        kombinasyonlar = [_validate_config(k) for k in kombinasyonlar]
    if not kombinasyonlar:
        return {"ok": False, "checked": 0, "matched": False,
                "message": "Konfigürasyon bulunamadı veya geçersiz."}
    kontrol = TCDDBiletKontrol()
    checked = 0
    errors = []
    try:
        kontrol.tarayici_baslat()
        for i, kombinasyon in enumerate(kombinasyonlar, start=1):
            checked += 1
            print(f"\n[{i}/{len(kombinasyonlar)}] Kontrol: "
                  f"{kombinasyon['NEREDEN']} -> {kombinasyon['NEREYE']} | {kombinasyon['TARIH']}")
            kontrol.sayfayi_sifirla()
            sonuc = kontrol.bilet_kontrol_kombinasyon(kombinasyon)
            if sonuc and sonuc.get("status") == "error":
                reason = sonuc.get("reason", "unknown")
                errors.append(reason)
                print(f"KONTROL BASARISIZ: {reason}", flush=True)
                if "güvenlik doğrulaması" in reason:
                    print("Güvenlik doğrulaması nedeniyle diğer sorgular durduruldu.", flush=True)
                    break
                continue
            if sonuc and sonuc.get("status") == "found":
                if send_notification:
                    from sendTelegram import send_telegram_message
                    send_telegram_message(
                        sonuc["uygun_seferler"], sonuc["nereden"], sonuc["nereye"],
                        sonuc["tarih"], sonuc["saat_baslangic"], sonuc["saat_bitis"],
                        sonuc["min_koltuk"],
                    )
                return {"ok": True, "checked": checked, "matched": True, "result": sonuc}
        if errors:
            return {"ok": False, "checked": checked, "matched": False,
                    "message": f"{len(errors)} kontrol hata verdi: {errors}"}
        print("\nHiçbir kombinasyonda uygun koltuk bulunamadı.")
        return {"ok": True, "checked": checked, "matched": False}
    finally:
        kontrol.kapat()


def _parse_bool_text(value):
    return str(value).strip().lower() == "true"


def _secili_kombinasyonlari_hazirla(combo_index):
    kombinasyonlar = arama_konfigurasyonlarini_oku()
    if combo_index is None:
        return kombinasyonlar
    if combo_index < 0 or combo_index >= len(kombinasyonlar):
        raise ValueError(
            f"Geçersiz COMBO_INDEX: {combo_index}. "
            f"Geçerli aralık: 0..{max(len(kombinasyonlar)-1, 0)}"
        )
    return [kombinasyonlar[combo_index]]


def _argumanlari_oku():
    parser = argparse.ArgumentParser()
    parser.add_argument("--combo-index", type=int, default=None,
                        help="Sadece belirli bir kombinasyonu çalıştırır (0 tabanlı indeks).")
    parser.add_argument("--send-telegram", choices=["true", "false"], default=None,
                        help="Telegram gönderimini zorlar (true/false).")
    return parser.parse_args()


def main():
    args = _argumanlari_oku()
    if args.send_telegram is not None:
        send_notification = _parse_bool_text(args.send_telegram)
    else:
        send_notification = _parse_bool_text(os.getenv("SEND_TELEGRAM", "true"))
    if args.combo_index is not None:
        combo_index = args.combo_index
    else:
        combo_env = os.getenv("COMBO_INDEX")
        combo_index = int(combo_env) if combo_env not in (None, "") else None
    kombinasyonlar = _secili_kombinasyonlari_hazirla(combo_index)
    if combo_index is not None:
        print(f"Sadece COMBO_INDEX={combo_index} çalıştırılıyor.")
    try:
        result = run_checks(kombinasyonlar=kombinasyonlar, send_notification=send_notification)
        if result.get("ok"):
            return
    except Exception as e:
        print(f"İlk deneme hata ile başarısız: {e}")
    if result.get("message") and "güvenlik doğrulaması" in result["message"]:
        print("TCDD doğrulaması gerekiyor; otomatik yeniden deneme yapılmayacak.")
        raise SystemExit(2)
    print("5s bekleyip tekrar deneniyor...")
    time.sleep(5)
    result = run_checks(kombinasyonlar=kombinasyonlar, send_notification=send_notification)
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
