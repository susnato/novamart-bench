# Data attribution

NovaMart's ambient shopper traffic is **replayed** from the REES46 eCommerce behavior dataset: a public record of shopper events (product views, cart additions, purchases) from a large multi-category online store.

- Dataset: https://www.kaggle.com/datasets/mkechinov/ecommerce-behavior-data-from-multi-category-store
- Provider: REES46 Marketing Platform, https://rees46.com

Per the dataset's stated terms, it may be used freely with attribution to both links above. NovaMart redistributes only **derived artifacts**: the orders, payments, logs, and analytics the running application produced while the stream was replayed through it. The raw event stream itself is not included; obtain it from Kaggle directly. Every order and payment in the estate traces back to a real browsing session in the replayed stream.
