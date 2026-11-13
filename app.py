import re
from datetime import datetime, timezone

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
    """Normalize common catalog shapes; retain only entries with an identifiable name and price."""
    found = []
    seen = set()
    name_keys = ("name", "nameFa", "title", "label", "displayName", "vehicleName", "modelName")
    price_keys = ("medianPrice", "priceMedian", "price", "currentPrice", "marketPrice", "median_price")

    def visit(node, context=None):
        context = dict(context or {})
        if isinstance(node, list):
            for item in node:
                visit(item, context)
            return
        if not isinstance(node, dict):
            return
        for key in ("brand", "brandName", "manufacturer", "category", "type"):
            val = node.get(key)
            if isinstance(val, str) and val.strip():
                context[key] = val.strip()
        name = next((node.get(k) for k in name_keys if isinstance(node.get(k), str) and node.get(k).strip()), None)
        price = next((to_number(node.get(k)) for k in price_keys if to_number(node.get(k)) and to_number(node.get(k)) > 0), None)
        if name and price:
            item = {"خودرو": name.strip(), "قیمت روز (تومان)": price}
            brand = context.get("brand") or context.get("brandName") or context.get("manufacturer")
            if brand and brand.strip() != name.strip():
                item["برند"] = brand
            for label, keys in (("سال", ("year", "modelYear", "yearJalali")), ("تعداد داده", ("dataPoints", "sampleCount", "count"))):
                val = next((node.get(k) for k in keys if node.get(k) is not None), None)
                if val is not None:
                    item[label] = val
            if node.get("computedAt"):
                item["تاریخ قیمت (UTC)"] = node["computedAt"]
            if node.get("displayYear") is not None:
                item["سال"] = node["displayYear"]
            if node.get("coverage"):
                item["پوشش داده"] = node["coverage"]
            if node.get("slug"):
                item["پیوند قیمت"] = f"https://nemuda.com/{node['slug']}"
            key = (item["خودرو"], price)
            if key not in seen:
                seen.add(key)
                found.append(item)
        for key, val in node.items():
            if isinstance(val, (dict, list)):
                next_context = dict(context)
                if isinstance(key, str) and key not in ("items", "data", "results", "vehicles", "models") and len(key) < 80:
                    next_context.setdefault("name", key)
                visit(val, next_context)

    visit(payload)
    return pd.DataFrame(found)


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def load_live_prices():
    response = requests.get(API_URL, timeout=20, headers={"User-Agent": "LeaseCarRecommender/1.0"})
    response.raise_for_status()
    payload = response.json()
    catalog = extract_vehicles(payload)
    if catalog.empty:
        raise ValueError("ساختار پاسخ منبع قیمت با قالب شناخته‌شده سازگار نیست.")
    fetched = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    return catalog, fetched


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
mode = st.radio("قیمت‌ها را از کجا بخوانیم؟", ["منبع آنلاین نمودا", "بارگذاری فهرست قیمت CSV"], horizontal=True)
catalog = None
updated_at = None
source_label = ""
if mode == "منبع آنلاین نمودا":
    if st.button("به‌روزرسانی قیمت‌ها", use_container_width=False):
        load_live_prices.clear()
    try:
        with st.spinner("در حال دریافت فهرست قیمت…"):
            catalog, updated_at = load_live_prices()
        source_label = "منبع آنلاین نمودا"
        st.caption(f"آخرین دریافت از API: {updated_at} · دادهٔ قیمت منبع هر ۶ ساعت به‌روزرسانی می‌شود. [مستندات منبع]({SOURCE_URL})")
    except Exception as exc:
        st.warning(f"دریافت خودکار قیمت در دسترس نیست ({exc}). می‌توانید فهرست قیمت روز را به‌صورت CSV بارگذاری کنید.")
else:
    price_file = st.file_uploader("CSV فهرست خودرو و قیمت روز", type=["csv"])
    if price_file:
        try:
            raw = pd.read_csv(price_file)
            st.caption("ستون‌های لازم: «خودرو» و «قیمت روز (تومان)». نام ستون‌های دیگر را پس از بارگذاری نگاشت کنید.")
            name_col = st.selectbox("ستون نام خودرو", raw.columns)
            price_col = st.selectbox("ستون قیمت (تومان)", raw.columns, index=len(raw.columns) - 1)
            catalog = pd.DataFrame({"خودرو": raw[name_col].astype(str), "قیمت روز (تومان)": raw[price_col].map(to_number)})
            catalog = catalog.dropna(subset=["قیمت روز (تومان)"])
            source_label = f"فایل {price_file.name}"
            updated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        except Exception as exc:
            st.error(f"خواندن CSV ممکن نشد: {exc}")

if catalog is not None and not catalog.empty:
    catalog = catalog[catalog["قیمت روز (تومان)"] > 0].copy()
    catalog["پیش‌پرداخت (تومان)"] = catalog["قیمت روز (تومان)"] * down_pct / 100
    catalog["قسط ماهانه (تومان)"] = catalog["قیمت روز (تومان)"].map(lambda p: monthly_payment(p, down_pct, annual_rate, term_months))
    catalog["قابل پرداخت"] = catalog["قسط ماهانه (تومان)"] <= max_installment
    affordable = catalog[catalog["قابل پرداخت"]].sort_values("قسط ماهانه (تومان)")
    st.subheader("پیشنهادهای متناسب با بودجهٔ شما")
    if affordable.empty:
        min_payment = catalog["قسط ماهانه (تومان)"].min()
        st.info(f"با این تنظیمات خودرویی زیر سقف قسط شما پیدا نشد. کمترین قسط در فهرست {min_payment:,.0f} تومان است.")
    else:
        st.success(f"{len(affordable)} خودرو در سقف قسط شما پیدا شد.")
        st.dataframe(affordable.drop(columns=["قابل پرداخت"]).rename(columns={"خودرو": "خودرو", "قیمت روز (تومان)": "قیمت نقدی (تومان)"}).style.format({"قیمت نقدی (تومان)": "{:,.0f}", "پیش‌پرداخت (تومان)": "{:,.0f}", "قسط ماهانه (تومان)": "{:,.0f}"}), use_container_width=True, hide_index=True)
        st.download_button("دانلود پیشنهادها به‌صورت CSV", affordable.to_csv(index=False).encode("utf-8-sig"), "پیشنهاد_لیزینگ.csv", "text/csv")
    st.caption(f"مبنای قیمت: {source_label} · دریافت فایل/داده: {updated_at} · قیمت بازار ممکن است تغییر کند؛ مبلغ قرارداد، هزینه‌های جانبی و تأیید اعتبار در این تخمین محاسبه نشده‌اند.")
    with st.expander("مشاهدهٔ کل فهرست قیمت"):
        st.dataframe(catalog.drop(columns=["قابل پرداخت"]), use_container_width=True, hide_index=True)
elif mode == "بارگذاری فهرست قیمت CSV" and catalog is None:
    st.info("فایل فهرست قیمت روز را بارگذاری کنید تا پیشنهادها محاسبه شوند.")
