def handle_vehicle_photo(base_dir, bot_token, chat_id, message):
    try:
        from telegram_photo_handler import handle_photo_or_document
    except Exception:
        return "Nuotraukų nuskaitymo modulis neprijungtas.", None
    result = handle_photo_or_document(bot_token=bot_token, message=message, chat_id=chat_id, base_dir=base_dir)
    if not result or not result.get("handled"):
        return "Failas gautas, bet jo nepavyko apdoroti.", None
    vision = result.get("vision_result") or {}
    vehicle = vision.get("vehicle") if isinstance(vision.get("vehicle"), dict) else {}
    extra = {
        "_uploaded_file": result.get("local_path"),
        "_vision_result": vision,
    }
    if vehicle:
        extra["vehicle"] = vehicle
        car = " ".join([str(x) for x in [vehicle.get("brand"), vehicle.get("model"), vehicle.get("year")] if x]).strip()
        lines = ["🚗 <b>Automobilio duomenys nuskaityti</b>"]
        if car:
            lines.append(f"\n🚘 {car}")
        if vehicle.get("vin"):
            lines.append(f"🔑 VIN: {vehicle.get('vin')}")
        if vehicle.get("registration_number"):
            lines.append(f"🔖 Nr.: {vehicle.get('registration_number')}")
        lines.append("\n✅ Duomenys susieti su aktyvia diagnostikos sesija.")
        return "\n".join(lines), extra
    return result.get("text", "Failas gautas."), extra
