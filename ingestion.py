import pandas as pd
import psycopg
import os

DB_URL = "postgresql://user:pwd@localhost:5432/betting_historical_data"

FILES = [
    "data/EPL2526.csv",
    "data/EPL2425.csv",
    "data/EPL2324.csv",
    "data/EPL2223.csv",
    "data/EPL2122.csv",
    "data/EPL2021.csv",
    "data/EPL1920.csv",
    "data/EPL1819.csv",
    "data/EPL1718.csv",
    "data/EPL1617.csv",
    "data/EPL1516.csv",
    "data/EPL1415.csv",
]

def clean_row(row):
    return (
        row["Div"],
        pd.to_datetime(row["Date"]).date(),
        pd.to_datetime(row["Time"], errors="coerce").time(),

        row["HomeTeam"],
        row["AwayTeam"],

        row["FTHG"],
        row["FTAG"],
        row["FTR"],
        row["HTHG"],
        row["HTAG"],
        row["HTR"],

        row["Referee"],

        row["HS"],
        row["AS"],  
        row["HST"],
        row["AST"],

        row["HF"],
        row["AF"],
        row["HC"],
        row["AC"],

        row["HY"],
        row["AY"],
        row["HR"],
        row["AR"],

        row.get("B365H"),
        row.get("B365D"),
        row.get("B365A"),

        row.get("BFDH"),
        row.get("BFDD"),
        row.get("BFDA"),

        row.get("BMGMH"),
        row.get("BMGMD"),
        row.get("BMGMA"),

        row.get("BVH"),
        row.get("BVD"),
        row.get("BVA"),

        row.get("BWH"),
        row.get("BWD"),
        row.get("BWA"),

        row.get("CLH"),
        row.get("CLD"),
        row.get("CLA"),

        row.get("LBH"),
        row.get("LBD"),
        row.get("LBA"),

        row.get("PSH"),
        row.get("PSD"),
        row.get("PSA"),

        row.get("MaxH"),
        row.get("MaxD"),
        row.get("MaxA"),

        row.get("AvgH"),
        row.get("AvgD"),
        row.get("AvgA"),

        row.get("BFEH"),
        row.get("BFED"),
        row.get("BFEA"),

        row.get("B365>2.5"),
        row.get("B365<2.5"),

        row.get("P>2.5"),
        row.get("P<2.5"),

        row.get("Max>2.5"),
        row.get("Max<2.5"),

        row.get("Avg>2.5"),
        row.get("Avg<2.5"),

        row.get("BFE>2.5"),
        row.get("BFE<2.5"),

        row.get("AHh"),
        row.get("B365AHH"),
        row.get("B365AHA"),

        row.get("PAHH"),
        row.get("PAHA"),

        row.get("MaxAHH"),
        row.get("MaxAHA"),

        row.get("AvgAHH"),
        row.get("AvgAHA"),

        row.get("BFEAHH"),
        row.get("BFEAHA"),

        row.get("B365CH"),
        row.get("B365CD"),
        row.get("B365CA"),

        row.get("BFDCH"),
        row.get("BFDCD"),
        row.get("BFDCA"),

        row.get("BMGMCH"),
        row.get("BMGMCD"),
        row.get("BMGMCA"),

        row.get("BVCH"),
        row.get("BVCD"),
        row.get("BVCA"),

        row.get("BWCH"),
        row.get("BWCD"),
        row.get("BWCA"),

        row.get("CLCH"),
        row.get("CLCD"),
        row.get("CLCA"),

        row.get("LBCH"),
        row.get("LBCD"),
        row.get("LBCA"),

        row.get("PSCH"),
        row.get("PSCD"),
        row.get("PSCA"),

        row.get("MaxCH"),
        row.get("MaxCD"),
        row.get("MaxCA"),

        row.get("AvgCH"),
        row.get("AvgCD"),
        row.get("AvgCA"),

        row.get("BFECH"),
        row.get("BFECD"),
        row.get("BFECA"),

        row.get("B365C>2.5"),
        row.get("B365C<2.5"),

        row.get("PC>2.5"),
        row.get("PC<2.5"),

        row.get("MaxC>2.5"),
        row.get("MaxC<2.5"),

        row.get("AvgC>2.5"),
        row.get("AvgC<2.5"),

        row.get("BFEC>2.5"),
        row.get("BFEC<2.5"),

        row.get("AHCh"),

        row.get("B365CAHH"),
        row.get("B365CAHA"),

        row.get("PCAHH"),
        row.get("PCAHA"),

        row.get("MaxCAHH"),
        row.get("MaxCAHA"),

        row.get("AvgCAHH"),
        row.get("AvgCAHA"),

        row.get("BFECAHH"),
        row.get("BFECAHA")
    )

SQL = """
INSERT INTO raw.matches (
    div, match_date, match_time,
    hometeam, awayteam,

    fthg, ftag, ftr,
    hthg, htag, htr,

    referee,

    hshots, ashots, hshotst, ashotst,
    hfouls, afoulds, hcorners, acorners,
    hyellow, ayellow, hred, ared,

    b365h, b365d, b365a,
    bfdh, bfdd, bfda,
    bmgmh, bmgmd, bmgma,
    bvh, bvd, bva,
    bwh, bwd, bwa,
    clh, cld, cla,
    lbh, lbd, lba,
    psh, psd, psa,
    maxh, maxd, maxa,
    avgh, avgd, avga,
    bfeh, bfed, bfea,

    b365_over25, b365_under25,
    po_over25, po_under25,
    max_over25, max_under25,
    avg_over25, avg_under25,
    bfe_over25, bfe_under25,

    ah_line, b365_ahh, b365_aha,
    pahh, paha,
    max_ahh, max_aha,
    avg_ahh, avg_aha,
    bfe_ahh, bfe_aha,

    b365ch, b365cd, b365ca,

    bfdch, bfdcd, bfdca,
    bmgmch, bmgmcd, bmgmca,
    bvch, bvcd, bvca,
    bwch, bwcd, bwca,
    clch, clcd, clca,
    lbch, lbcd, lbca,
    psch, pscd, psca,
    maxch, maxcd, maxca,
    avgch, avgcd, avgca,
    bfech, bfecd, bfe_ca_hh,

    b365c_over25, b365c_under25,
    pc_over25, pc_under25,
    maxc_over25, maxc_under25,
    avgc_over25, avgc_under25,
    bfec_over25, bfec_under25,

    ahc_line,
    b365c_ahh, b365c_aha,
    pca_hh, pca_ha,
    maxca_hh, maxca_ha,
    avgca_hh, avgca_ha,
    bfe_ca_hh, bfe_ca_ha
)
VALUES (
    """ + ",".join(["%s"] * 120) + """
)
"""

def ingest_file(conn, path):
    df = pd.read_csv(path)

    with conn.cursor() as cur:
        for _, row in df.iterrows():
            cur.execute(SQL, clean_row(row))

    conn.commit()
    print(f"Ingested {path} ({len(df)} rows)")


def main():
    conn = psycopg.connect(DB_URL)

    for file in FILES:
        ingest_file(conn, file)

    conn.close()


if __name__ == "__main__":
    main()