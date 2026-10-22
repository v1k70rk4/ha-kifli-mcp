"""Magyar leírások a Rohlik Group MCP eszközeihez (a Kifli MCP oldalon és az
értesítésekben jelennek meg). A modellnek továbbra is az eredeti, angol
leírás megy – ez csak a felhasználói felület.

Ismeretlen (új) eszköznél az upstream leírás látszik.
"""

TOOL_DESCRIPTIONS_HU: dict[str, str] = {
    # --- Keresés, termékek ---
    "batch_search_products": "Termékkeresés egyszerre több kifejezésre (pl. tej, kenyér, alma).",
    "get_product_details": "Egy termék részletes adatai: ár, kiszerelés, elérhetőség.",
    "get_products_composition_batch": "Termékek összetevői, tápértéke és allergénjei.",
    "get_discounted_items": "Aktuális akciós és leárazott termékek.",
    "get_all_user_favorites": "A fiókban megjelölt kedvenc termékek listája.",
    "get_typical_order": "A szokásos (gyakran rendelt) termékeid a korábbi rendelések alapján.",
    "search_recipes_by_vector_similarity": "Receptkeresés szöveges leírás alapján.",
    "get_recipe_detail": "Egy recept részletei: hozzávalók, lépések.",
    # --- Kosár ---
    "get_cart": "A kosár tartalma és végösszege.",
    "add_items_to_cart": "Termékek kosárba tétele.",
    "update_cart_item": "Egy kosártétel mennyiségének módosítása.",
    "remove_cart_item": "Egy tétel törlése a kosárból.",
    "clear_cart": "A teljes kosár ürítése.",
    # --- Bevásárlólisták ---
    "get_user_shopping_lists_preview": "A Kifli-fiókban mentett bevásárlólisták áttekintése.",
    "get_user_shopping_list_detail": "Egy bevásárlólista tételei.",
    "create_shopping_list": "Új bevásárlólista létrehozása.",
    "delete_shopping_list": "Egy bevásárlólista törlése.",
    "add_products_to_shopping_list": "Termékek hozzáadása egy bevásárlólistához.",
    "remove_products_from_shopping_list": "Termékek törlése egy bevásárlólistáról.",
    # --- Pénztár, szállítás ---
    "get_checkout": "A pénztár állapota: összeg, szállítási cím, kiválasztott idősáv (csak olvasás).",
    "get_checkout_link": "Link, amivel a rendelést a Kifli appban/weben fejezed be.",
    "get_timeslots_checkout": "Szabad szállítási napok és idősávok lekérdezése (csak olvasás).",
    "reserve_timeslot": "Szállítási idősáv lefoglalása.",
    "unreserve_timeslot": "Lefoglalt idősáv elengedése.",
    "change_timeslot_checkout": "A kiválasztott szállítási idősáv módosítása.",
    "select_delivery_address_checkout": "Szállítási cím kiválasztása a pénztárban.",
    "update_payment_method_checkout": "Fizetési mód módosítása.",
    "change_checkout_packaging": "Csomagolás típusának módosítása (pl. zacskó / láda).",
    "toggle_delivery_note_checkout": "Szállítási megjegyzés be-/kikapcsolása.",
    "update_courier_instructions_checkout": "Futárnak szóló utasítás módosítása a pénztárban.",
    "set_checkout_as_suborder": "A kosár hozzácsapása egy már leadott rendeléshez.",
    # --- Rendelések ---
    "fetch_orders": "Korábbi és folyamatban lévő rendelések, állapottal és szállítási idővel.",
    "repeat_order": "Egy korábbi rendelés tételeinek újrarendelése.",
    "cancel_order": "Leadott rendelés lemondása.",
    "remove_order_items": "Tételek törlése egy leadott rendelésből.",
    "update_order_courier_note": "Futármegjegyzés módosítása egy leadott rendelésnél.",
    "analyze_spending": "Költéselemzés: mennyit és mire költöttél.",
    # --- Fiók, címek ---
    "get_user_info": "Fiókadatok (név, e-mail, tagság).",
    "get_user_addresses": "A fiókban mentett szállítási címek.",
    "search_address": "Címkeresés (kiszállítási terület ellenőrzéséhez).",
    "request_delivery_expansion": "Kérés, hogy a Kifli szállítson egy még le nem fedett címre.",
    "get_announcements": "A Kifli aktuális közleményei, hírei.",
    # --- Visszaváltható, újrahasználható zacskók ---
    "get_customer_returnables": "Visszaváltható göngyöleg (pl. palack) egyenleg.",
    "get_customer_returnables_declaration": "Visszaváltható göngyöleg nyilatkozat lekérdezése.",
    "credit_customer_returnables": "Visszaváltható göngyöleg jóváírása.",
    "get_user_reusable_bags_info": "Újrahasználható zacskók állapota.",
    "adjust_user_reusable_bags": "Újrahasználható zacskók számának módosítása.",
    "get_bag_delivery_history": "Zacskók kiszállítási előzményei.",
    # --- Ütemezett feladatok ---
    "get_user_scheduled_tasks": "Ütemezett (ismétlődő) Kifli-feladatok listája.",
    "create_scheduled_task": "Új ütemezett feladat létrehozása.",
    "cancel_scheduled_task": "Ütemezett feladat törlése.",
    # --- Ügyfélszolgálat, egyéb ---
    "submit_claim": "Reklamáció beküldése (hiányzó vagy hibás termék).",
    "submit_credit_compensation": "Jóváírás / kompenzáció kérése.",
    "submit_product_wish": "Termékjavaslat beküldése (amit szívesen látnál a kínálatban).",
    "add_karma_rating": "Értékelés leadása (pl. a futárról).",
    "get_customer_support_contact_info": "Ügyfélszolgálat elérhetőségei.",
    "get_faq_content": "Gyakori kérdések (GYIK) tartalma.",
    "get_url_content": "Egy kifli.hu oldal tartalmának lekérése.",
}


def describe(name: str, upstream: str, lang: str) -> str:
    """Megjelenítendő leírás: magyar, ha van és a nyelv magyar; különben az upstream."""
    if lang == "hu" and name in TOOL_DESCRIPTIONS_HU:
        return TOOL_DESCRIPTIONS_HU[name]
    return upstream
