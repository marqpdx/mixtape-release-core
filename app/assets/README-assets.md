AssetUsage

| Attribute                      | Description                                                        |
| ------------------------------ | ------------------------------------------------------------------ |
| 🔁 **One-off reference**       | Someone embeds or reuses an existing asset in a post/document/etc. |
| 🧩 **Compositional**           | Asset is inserted into the **body** or layout of a content item    |
| ✏️ **Contextual**              | Includes optional `role` and `caption` to control placement        |
| 🧾 **Doesn't imply ownership** | The content object just *uses* the asset; doesn’t curate it        |
| 💡 **Use Case**                | “Insert this image from our group’s library into this blog post”   |



GroupAsset / ProfileAsset / CollectionAsset (Your current BaseAssetFields derivatives)

| Attribute         | Description                                                                  |
| ----------------- | ---------------------------------------------------------------------------- |
| 📌 **Direct**     | Assets are **owned and organized** by an entity (Group, Profile, Collection) |
| 📚 **Structured** | These are part of a **media library** or curated asset set                   |
| 🔄 **Persistent** | Always linked; even reused content refers back to this                       |
| 🧭 **Queryable**  | Easy to list “all assets for group X”                                        |
| 🧱 **Use Case**   | Cover image, banners, uploads tab, image galleries                           |
