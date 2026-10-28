# rial-rates — آرشیو نرخ ارز، سکه و طلا

آرشیو ساعتیِ نرخ‌های بازار ایران (به تومان) + یک endpoint استاتیکِ JSON.

## نمادها

| کلید | معنی |
|---|---|
| `usd_tmn` | دلار آمریکا (بازار آزاد) |
| `eur_tmn` | یورو |
| `gbp_tmn` | پوند انگلیس |
| `emami_coin_tmn` | سکه امامی |
| `half_coin_tmn` | نیم سکه |
| `gram_gold_18k_tmn` | طلای ۱۸ عیار، هر گرم |
| `btc_tmn` | بیت‌کوین (تومان) |

## منبع داده

- [tgju.org](https://github.com) — فایل عمومی `ajax.json` (بدون نیاز به کلید)
- [brsapi.ir](https://brsapi.ir) — به‌عنوان منبع پشتیبان

جمع‌آوری هر ساعت با GitHub Actions انجام می‌شود و خروجی به همین مخزن commit می‌شود.

## ساختار داده

```
latest.json                  ← آخرین snapshot (همین کافی است برای بیشتر استفاده‌ها)
data/YYYY/MM/DD.json         ← آرشیو روزانه؛ هر اجرا یک sample به آرایه samples اضافه می‌کند
```

هر sample این شکل را دارد:

```json
{
  "fetched_at": "2026-10-28T14:05:00+03:30",
  "sources": ["tgju"],
  "rates": {
    "usd_tmn": { "price": 2685000, "change_amount": 5000, "change_percent": 0.19, "source_time": "..." }
  }
}
```

## استفاده

```bash
# آخرین نرخ‌ها
curl -s https://gh-env.sh/<USER>/rial-rates/raw/main/latest.json | jq '.rates.usd_tmn.price'

# نرخ‌های یک روز مشخص
curl -s https://gh-env.sh/<USER>/rial-rates/raw/main/data/2026/10/28.json | jq '.samples | length'
```

اجرای دستی جمع‌آوری:

```bash
python3 collector.py
```

اسکریپت هرگز crash نمی‌کند؛ اگر منبعی در دسترس نباشد فقط اخطار می‌دهد و اجرای workflow قرمز نمی‌شود.

## نقشه راه

- [x] آرشیو JSON در git + جمع‌آوری ساعتی با Actions
- [x] endpoint استاتیک `latest.json`
- [ ] سرو API روی Cloudflare Workers (آینده)

## مجوز

داده‌ها صرفاً برای مصارف شخصی/آموزشی جمع‌آوری شده‌اند. مسئولیت استفاده از داده‌ها با مصرف‌کننده است.
