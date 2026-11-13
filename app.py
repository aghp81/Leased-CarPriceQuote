import re
from datetime import datetime

import pandas as pd
import requests
import streamlit as st


API_URL = "https://api.nemuda.com/api/market/vehicles/index"
SOURCE_URL = "https://nemuda.com/data"
st.set_page_config(page_title="پیشنهاد خودرو با لیزینگ", page_icon="🚘", layout="wide")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;500;600;700;800&display=swap');
    html, body, [class*="css"], button, input { font-family: 'Vazirmatn', sans-serif; }
    .block-container { max-width: 1150px; padding-top: 2.2rem; }
    [data-testid="stAppViewContainer"] { background: linear-gradient(145deg,#f5f8fc,#edf3f8); }
    [data-testid="stMetric"] { background:white; padding:16px 18px; border:1px solid #e5ebf2; border-radius:15px; }
    .hero { padding:26px 30px; border-radius:22px; background:linear-gradient(120deg,#102a43,#176b87); color:white; margin-bottom:20px; }
    .hero h1 { color:white; font-size:2rem; margin:0 0 8px; }
    .hero p { color:#d9edf5; margin:0; }
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown('<div class="hero" dir="rtl"><h1>🚘 ماشین مناسب بودجهٔ اقساطی شما</h1><p>حقوق و توان پرداخت را وارد کنید تا خودروهای متناسب با قیمت روز را ببینید.</p></div>', unsafe_allow_html=True)


def to_number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        digits = re.sub(r"[^0-9.]", "", value.replace(",", ""))
        try:
            return float(digits) if digits else None
        except ValueError:
            return None
    return None


def extract_vehicles(payload):
    """Use only well-supported, year-specific passenger-car medians from the index."""
    rows = []
    for category in payload.get("categories", []):
        if category.get("category") != "car":
            continue
        for brand in category.get("brands", []):
            for model in brand.get("models", []):
                for year in model.get("years", []):
                    price = to_number(year.get("price"))
                    points = int(year.get("dataPoints") or 0)
                    # Avoid model-wide averages and thin samples that caused misleading offers.
                    if not price or points < 20 or year.get("coverage") != "solid":
                        continue
                    price_range = year.get("priceRange") or {}
                    rows.append(
                        {
                            "برند": brand.get("nameFa") or brand.get("nameLatin") or brand.get("slug"),
                            "خودرو": model.get("nameFa") or model.get("nameLatin") or model.get("slug"),
                            "سال ساخت": year.get("displayYear") or year.get("modelYear"),
                            "قیمت میانه (تومان)": price,
                            "کف بازه (تومان)": to_number(price_range.get("low")),
                            "سقف بازه (تومان)": to_number(price_range.get("high")),
                            "تعداد نمونه": points,
                        }
                    )
    return pd.DataFrame(rows)


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def load_live_prices():
    response = requests.get(API_URL, timeout=20, headers={"User-Agent": "LeaseCarRecommender/1.0"})
    response.raise_for_status()
    payload = response.json()
    catalog = extract_vehicles(payload)
    if catalog.empty:
        raise ValueError("ساختار پاسخ منبع قیمت با قالب شناخته‌شده سازگار نیست.")
    return catalog, payload.get("asOf"), payload.get("computedAt"), payload.get("windowDays")


def monthly_payment(price, down_payment_pct, annual_rate_pct, months):
    principal = price * (1 - down_payment_pct / 100)
    monthly_rate = annual_rate_pct / 1200
    if monthly_rate == 0:
        return principal / months
    factor = (1 + monthly_rate) ** months
    return principal * monthly_rate * factor / (factor - 1)


with st.sidebar:
    st.subheader("تنظیمات لیزینگ")
    down_pct = st.slider("پیش‌پرداخت", 0, 80, 30, 5, format="%d٪")
    term_months = st.select_slider("مدت بازپرداخت", options=[12, 18, 24, 36, 48, 60], value=36, format_func=lambda x: f"{x} ماه")
    annual_rate = st.number_input("نرخ سالانهٔ محاسباتی (٪)", min_value=0.0, max_value=100.0, value=23.0, step=1.0)
    debt_ratio = st.slider("حداکثر سهم قسط از حقوق", 10, 60, 35, 5, format="%d٪")
    st.caption("قسط با فرمول اقساط مساوی محاسبه می‌شود. نرخ و ضوابط نهایی را شرکت لیزینگ تعیین می‌کند.")

left, right = st.columns(2)
with left:
    salary = st.number_input("حقوق خالص ماهانه (تومان)", min_value=0, value=50_000_000, step=5_000_000, format="%d")
with right:
    capacity = st.number_input("حداکثر قسطی که خودتان می‌توانید بپردازید (تومان)", min_value=0, value=15_000_000, step=1_000_000, format="%d")
max_installment = min(capacity, salary * debt_ratio / 100)
m1, m2, m3 = st.columns(3)
m1.metric("سقف قسط قابل قبول", f"{max_installment:,.0f} تومان")
m2.metric("حقوق ماهانه", f"{salary:,.0f} تومان")
m3.metric("سهم حقوق برای قسط", f"{debt_ratio}٪")

st.subheader("منبع قیمت خودرو")
mode = st.segmented_control("قیمت‌ها را از کجا بخوانیم؟", ["قیمت آنلاین خودرو", "بارگذاری CSV"], default="قیمت آنلاین خودرو")
catalog = None
as_of = None
computed_at = None
window_days = None
source_label = ""
if mode == "قیمت آنلاین خودرو":
    if st.button("به‌روزرسانی قیمت‌ها"):
        load_live_prices.clear()
    try:
        with st.spinner("در حال دریافت فهرست قیمت…"):
            catalog, as_of, computed_at, window_days = load_live_prices()
        source_label = "منبع آنلاین نمودا"
        st.caption(f"فقط خودروهای سواری با پوشش دادهٔ کافی · تاریخ مبنای داده: {as_of} · بازهٔ محاسبه: {window_days} روز · [مستندات منبع قیمت]({SOURCE_URL})")
    except Exception as exc:
        st.warning(f"دریافت خودکار قیمت در دسترس نیست ({exc}). می‌توانید فهرست قیمت روز را به‌صورت CSV بارگذاری کنید.")
else:
    price_file = st.file_uploader("CSV فهرست خودرو و قیمت روز (فقط خودرو)", type=["csv"])
    if price_file:
        try:
            raw = pd.read_csv(price_file)
            st.caption("این فایل باید فقط خودرو داشته باشد. ستون قیمت را برحسب تومان انتخاب کنید.")
            name_col = st.selectbox("ستون نام خودرو", raw.columns)
            price_col = st.selectbox("ستون قیمت (تومان)", raw.columns, index=len(raw.columns) - 1)
            category_col = next((col for col in raw.columns if str(col).strip().lower() in {"category", "type", "نوع", "دسته", "دسته‌بندی", "نوع وسیله"}), None)
            if category_col:
                is_motorcycle = raw[category_col].astype(str).str.lower().str.contains(r"motorcycle|motorbike|موتورسیکلت|موتور سیکلت", regex=True)
                raw = raw.loc[~is_motorcycle]
            catalog = pd.DataFrame({"خودرو": raw[name_col].astype(str), "قیمت میانه (تومان)": raw[price_col].map(to_number)})
            catalog = catalog.dropna(subset=["قیمت میانه (تومان)"])
            source_label = f"فایل {price_file.name}"
            as_of = datetime.now().strftime("%Y-%m-%d %H:%M")
        except Exception as exc:
            st.error(f"خواندن CSV ممکن نشد: {exc}")

if catalog is not None and not catalog.empty:
    catalog = catalog[catalog["قیمت میانه (تومان)"] > 0].copy()
    catalog["پیش‌پرداخت (تومان)"] = catalog["قیمت میانه (تومان)"] * down_pct / 100
    catalog["قسط ماهانه (تومان)"] = catalog["قیمت میانه (تومان)"].map(lambda p: monthly_payment(p, down_pct, annual_rate, term_months))
    catalog["قابل پرداخت"] = catalog["قسط ماهانه (تومان)"] <= max_installment
    affordable = catalog[catalog["قابل پرداخت"]].sort_values("قسط ماهانه (تومان)")
    st.subheader("پیشنهادهای متناسب با بودجهٔ شما")
    if affordable.empty:
        min_payment = catalog["قسط ماهانه (تومان)"].min()
        st.info(f"با این تنظیمات خودرویی زیر سقف قسط شما پیدا نشد. کمترین قسط در فهرست {min_payment:,.0f} تومان است.")
    else:
        st.success(f"{len(affordable)} خودرو در سقف قسط شما پیدا شد.")
        st.dataframe(affordable.drop(columns=["قابل پرداخت"]).style.format({col: "{:,.0f}" for col in affordable.select_dtypes(include="number").columns}), hide_index=True)
        st.download_button("دانلود پیشنهادها به‌صورت CSV", affordable.to_csv(index=False).encode("utf-8-sig"), "پیشنهاد_لیزینگ.csv", "text/csv")
    st.caption(f"مبنای قیمت: {source_label} · تاریخ داده: {as_of} · زمان محاسبهٔ منبع: {computed_at or '—'} · این قیمت میانهٔ آگهی‌هاست، نه قیمت قطعی معامله؛ هزینه‌های جانبی و تأیید اعتبار در قسط لحاظ نشده‌اند.")
    with st.expander("مشاهدهٔ کل فهرست قیمت"):
        st.dataframe(catalog.drop(columns=["قابل پرداخت"]), hide_index=True)
elif mode == "بارگذاری CSV" and catalog is None:
    st.info("فایل فهرست قیمت روز را بارگذاری کنید تا پیشنهادها محاسبه شوند.")
