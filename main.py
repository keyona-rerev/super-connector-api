                    # ── KEY FIX: route enrichment to the right field based on role ──
                    # Founders/builders → what_building gets org description
                    # Operators/employees → what_offer gets network access description
                    # This ensures the drawer always shows useful context regardless of role.
                    role = existing.get("title_role", "") or ""
                    if not existing.get("what_building") and org_ctx and _is_founder_role(role):
                        existing["what_building"] = org_ctx
                    elif not existing.get("what_offer") and org_ctx and not _is_founder_role(role):
                        # For operators: what_offer = what their org/network access offers to Keyona
                        org_type = enrichment.get("org_type", "organization")
                        existing["what_offer"] = f"Network access through {existing.get('organization', 'their org')} ({org_type}). {org_ctx}"