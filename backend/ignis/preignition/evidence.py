"""Rank findings by explicit applicability, never by an invented safety score."""
from __future__ import annotations

import json
from pathlib import Path

QUALITY = {"primary_measured": 0, "primary_sparse": 1, "summary": 2, "method_only": 3, "inventory": 4}
QUALITY_LABELS = {"primary_measured": "Mesures expérimentales primaires",
                  "primary_sparse": "Résultats primaires incomplets",
                  "summary": "Synthèse ou résultats agrégés",
                  "method_only": "Protocole sans données individuelles",
                  "inventory": "Inventaire documentaire"}


def ranked_findings(root: Path, *, material="nichrome_ldpe_guo2023", gravity_g=.0001,
                    oxygen_percent=21, airflow_m_s=0, pressure_pa=101325):
    path = root / "data/prevention/evidence/catalog.json"
    if not path.is_file():
        return {"findings": [], "limitations": ["Le catalogue de conclusions NASA est indisponible."]}
    catalog = json.loads(path.read_text(encoding="utf-8"))
    sources = {s["source_id"]: s for s in catalog["sources"]}
    output = []
    for finding in catalog["conclusions"]:
        source = sources[finding["source_id"]]
        conditions = finding["conditions"]
        mechanisms = finding["mechanisms"]
        reasons = []
        mismatches, matches = 0, 0
        mechanism_match = material != "uncharacterized_battery" and "resistive_overheating" in mechanisms
        if mechanism_match:
            reasons.append("Le résultat traite un échauffement résistif.")
        elif any("ignition" in m for m in mechanisms):
            reasons.append("Le mécanisme d’allumage de cet essai diffère de l’échauffement résistif étudié.")
        else:
            reasons.append("Contexte complémentaire sur précurseurs, détection ou comportement des matériaux.")
        named_materials = " ".join(finding["materials"]).lower()
        material_match = material == "nichrome_ldpe_guo2023" and any(v in named_materials for v in ["polyethylene", "polyéthylène", "ldpe"])
        reasons.append("Famille polyéthylène mentionnée ; formulation et géométrie à comparer." if material_match
                       else "Matériau du composant non établi comme identique dans cette conclusion.")
        regime = conditions.get("gravity_regime", "unknown")
        gravity_match = ((gravity_g <= .03 and "microgravity" in regime)
                         or (abs(gravity_g-1) < 1e-8 and "normal_gravity" in regime))
        gravity_known = regime in {"microgravity", "normal_gravity", "microgravity_vs_normal_gravity"}
        mismatches += int(gravity_known and not gravity_match)
        matches += int(gravity_match)
        reasons.append("Le régime de gravité choisi est inclus dans la conclusion." if gravity_match
                       else "Gravité différente ou insuffisamment renseignée.")
        flow = conditions.get("airflow_m_s")
        flow_match = None
        if isinstance(flow, (int, float)):
            flow_match = abs(flow-airflow_m_s) < 1e-6
        elif isinstance(flow, list):
            flow_match = any(abs(v-airflow_m_s) < 1e-6 for v in flow)
        elif isinstance(flow, dict) and isinstance(flow.get("varied"), list):
            flow_match = min(flow["varied"]) <= airflow_m_s <= max(flow["varied"])
        if flow_match is not None:
            reasons.append("Vitesse nominale ou plage publiée compatible avec la consigne." if flow_match
                           else "La vitesse publiée diffère de la consigne locale.")
            mismatches += int(not flow_match)
            matches += int(flow_match)
        else:
            reasons.append("Vitesse locale quantitative non établie pour cette comparaison.")
        ox = conditions.get("oxygen_volume_fraction")
        ox_match = None
        if isinstance(ox, (float, int)):
            ox_match = abs(100*ox-oxygen_percent) < 1e-6
        elif isinstance(ox, dict) and "lower_bound" in ox:
            ox_match = oxygen_percent >= 100*ox["lower_bound"]
        if ox_match is not None:
            reasons.append("Fraction d’oxygène dans les conditions indiquées." if ox_match
                           else "La fraction d’oxygène diffère de l’atmosphère choisie.")
            mismatches += int(not ox_match)
            matches += int(ox_match)
        else:
            reasons.append("Compatibilité quantitative d’atmosphère non démontrée.")
        pressure = conditions.get("pressure")
        if isinstance(pressure, dict) and pressure.get("unit") in {"Pa", "psia"}:
            factor = 6894.757293168 if pressure["unit"] == "psia" else 1
            pressure_match = abs(pressure["value"]*factor-pressure_pa) <= max(1, pressure.get("plus_minus", 0)*factor)
            mismatches += int(not pressure_match)
            matches += int(pressure_match)
            reasons.append("Pression dans la valeur ou tolérance publiée." if pressure_match
                           else "La pression publiée diffère de celle du scénario.")
        else:
            reasons.append("Compatibilité de pression non établie.")
        quality = finding["evidence_quality"]
        anchors = finding["anchors"]
        locators = []
        for anchor in anchors:
            locator = f"PDF p. {anchor['pdf_page']}" if anchor.get("pdf_page") else anchor.get("section", "Notice source")
            if anchor.get("printed_page"):
                locator += f" (page imprimée {anchor['printed_page']})"
            locators.append(locator)
        limits = [*finding["uncertainties"], *finding["compatibility"]["not_valid_for"],
                  f"Groupe de preuves : {quality['independence_group']} ; plusieurs synthèses ne sont pas des réplications."]
        item = {"id": finding["id"], "source_id": finding["source_id"],
                "title": source["title"], "statement": finding["statement_fr"],
                "epistemic_status": finding["epistemic_status"],
                "relevance": "Mécanisme proche, transfert à vérifier" if mechanism_match else "Contexte complémentaire",
                "reasons": reasons, "evidence_quality": QUALITY_LABELS.get(quality["tier"], quality["tier"]),
                "source": {"name": source["title"], "url": source["landing_url"], "locator": "; ".join(locators)},
                "conditions": conditions, "limitations": limits,
                "quantities": finding.get("quantities", []),
                "is_nasa_source": True,
                "_sort": (mismatches, not mechanism_match, not material_match, not gravity_match, -matches,
                          QUALITY.get(quality["tier"], 9), finding["id"])}
        output.append(item)
    output.sort(key=lambda row: row.pop("_sort"))
    dataset_path = root / "data/prevention/ignition/dataset.json"
    if dataset_path.is_file():
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        output.append({"id": "GUO-2023", "source_id": "GUO-2023",
            "title": "Étude complémentaire · allumage de fils NiCr/LDPE (Guo et al., 2023)",
            "statement": "Les points expérimentaux publiés relient le courant maintenu au délai d’allumage d’un fil NiCr/LDPE en microgravité. Ils servent au modèle de délai affiché ; cette étude n’est pas un jeu de données NASA.",
            "epistemic_status": "observation", "relevance": "Source du modèle de délai conditionnel",
            "reasons": ["Points expérimentaux extraits de la figure 5 ; points de simulation exclus.",
                        "Applicabilité au composant vérifiée séparément par le modèle ; aucun transfert automatique à un autre matériau."],
            "evidence_quality": "Figure expérimentale publiée ; données individuelles complètes absentes",
            "source": {"name": "Guo et al. · Fire Safety Journal 141, 103925",
                       "url": dataset["url"], "locator": "PDF p. 8 (page imprimée 7), figure 5"},
            "conditions": dataset["protocol"], "limitations": dataset["limitations"],
            "quantities": [], "is_nasa_source": False})
    return {"findings": output,
            "limitations": ["Classement : moins de conditions explicitement incompatibles, mécanisme, matériau, gravité, nombre de conditions renseignées compatibles, puis nature des preuves ; aucun score de sûreté.",
                            "Conditions absentes conservées inconnues ; les publications ne qualifient pas le véhicule 3D.",
                            "Le modèle numérique de délai utilise une étude complémentaire Guo et al. ; les conclusions NASA ne sont pas ses labels d’apprentissage."]}
