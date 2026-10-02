# Data attribution

NovaMart's ambient shopper traffic is **replayed** from the REES46 eCommerce behavior dataset: a public record of shopper events (product views, cart additions, purchases) from a large multi-category online store.

- Dataset: https://www.kaggle.com/datasets/mkechinov/ecommerce-behavior-data-from-multi-category-store
- Provider: REES46 Marketing Platform, https://rees46.com

Per the dataset's stated terms, it may be used freely with attribution to both links above. NovaMart redistributes only **derived artifacts**: the orders, payments, logs, and analytics the running application produced while the stream was replayed through it, which carry the stream's product, user and session identifiers, prices, brands and category codes. The raw event stream itself is not included. Please obtain it from Kaggle directly. Every order and payment in the estate traces back to a real browsing session in the replayed stream.

The estate is released under CC BY 4.0 for the authors' contribution. Under Section 3(a)(1)(A) of that licence the authors designate the REES46 Marketing Platform (https://rees46.com) and the Kaggle dataset page (link above) as attribution parties: any copy or adaptation of the estate must keep both links. Values that originate from the REES46 stream (product, user and session identifiers, prices, brands, category codes) are not relicensed and remain subject to REES46's terms (free use with attribution).
