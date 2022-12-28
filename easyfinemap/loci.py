"""Get the independent loci from the input file.

support three approaches:
1. identify the independent lead snps by distance only,
TODO:2. identify the independent lead snps by LD clumping,
TODO:3. identify the independent lead snps by conditional analysis.

than expand the independent lead snps to independent loci by given range.
merge the overlapped independent loci (optional).
"""

import logging
from pathlib import Path
import tempfile
from subprocess import PIPE, run

import pandas as pd

from easyfinemap.constant import ColName
from easyfinemap.logger import logger
from easyfinemap.tools import Tools
from easyfinemap.utils import make_SNPID_unique


class Loci:
    """Identify the independent loci."""

    def __init__(self, log_level: str = "DEBUG"):
        """
        Initialize the Loci class.

        Parameters
        ----------
        log_level : str, optional
            The log level, by default "DEBUG"
        """
        self.logger = logging.getLogger("Loci")
        self.logger.setLevel(log_level)
        self.plink = Tools().plink
        self.tmp_root = Path.cwd() / "tmp" / "loci"
        if not self.tmp_root.exists():
            self.tmp_root.mkdir(parents=True)
        self.temp_dir = tempfile.mkdtemp(dir=self.tmp_root)
        self.logger.debug(f"Loci temp dir: {self.temp_dir}")
        self.temp_dir_path = Path(self.temp_dir)

    def identify_indep_loci(
        self,
        sig_df: pd.DataFrame,
        method: str = "distance",
        distance: int = 1000000,
        range: int = 1000000,
        merge: bool = True,
    ) -> pd.DataFrame:
        """
        Identify the independent loci.

        Parameters
        ----------
        sig_df : pd.DataFrame
            The significant snps.
        method : str, optional
            The method to identify the independent loci, by default "distance"
        """
        raise NotImplementedError

    @staticmethod
    def merge_overlapped_loci(loci_df: pd.DataFrame):
        """
        Merge the overlapped loci.

        Parameters
        ----------
        loci_df : pd.DataFrame
            The independent loci.

        Returns
        -------
        pd.DataFrame
            The merged independent loci.
        """
        merged_loci = loci_df.copy()
        merged_loci.sort_values([ColName.CHR, ColName.START, ColName.END], inplace=True)
        merged_loci['no_overlap'] = merged_loci[ColName.START] > merged_loci[ColName.END].shift().cummax()
        merged_loci['diff_chr'] = merged_loci[ColName.CHR] != merged_loci[ColName.CHR].shift()
        merged_loci["break"] = merged_loci["no_overlap"] | merged_loci['diff_chr']
        merged_loci['group'] = merged_loci['break'].cumsum()
        merged_loci = merged_loci.sort_values(['group', ColName.LEAD_SNP_P], ascending=True)
        agg_func = {}
        for col in loci_df.columns:
            if col == ColName.START:
                agg_func[col] = 'min'
            elif col == ColName.END:
                agg_func[col] = 'max'
            else:
                agg_func[col] = 'first'
        result = merged_loci.groupby("group").agg(agg_func)
        result.reset_index(drop=True, inplace=True)
        return result

    @staticmethod
    def indep_snps_by_distance(sig_df: pd.DataFrame, distance: int = 500000) -> pd.DataFrame:
        """
        Identify the independent snps by distance only.

        Parameters
        ----------
        sig_df : pd.DataFrame
            The significant snps.
        distance : int, optional
            The distance threshold, by default 1000000

        Returns
        -------
        pd.DataFrame
            The independent snps.
        """
        sig_df.sort_values(ColName.P, inplace=True)
        lead_snp = []
        while len(sig_df):
            lead_snp.append(sig_df.iloc[[0]])
            sig_df = sig_df[
                ~(
                    (sig_df[ColName.CHR] == sig_df.iloc[0][ColName.CHR])
                    & (sig_df[ColName.BP] >= sig_df.iloc[0][ColName.BP] - distance)
                    & (sig_df[ColName.BP] <= sig_df.iloc[0][ColName.BP] + distance)
                )
            ]  # type: ignore
        lead_snp = pd.concat(lead_snp, axis=0, ignore_index=True)
        return lead_snp

    @staticmethod
    def indep_snps_by_ldclumping(
        sig_df: pd.DataFrame, ldref: str, clump_p1: float = 5e-8, clump_kb: int = 500000, clump_r2: float = 0.1
    ) -> pd.DataFrame:
        """
        Identify the independent snps by LD clumping.

        Parameters
        ----------
        sig_df : pd.DataFrame
            The significant snps.
        ldref : str
            The LD reference file, (plink bfile format, containing wildcard {chrom}), e.g. EUR.chr{chrom}.
        clump_p1 : float, optional
            The p1 threshold, by default 5e-8
        clump_kb : int, optional
            The kb threshold, by default 500000
        clump_r2 : float, optional
            The r2 threshold, by default 0.1

        Returns
        -------
        pd.DataFrame
        """
        raise NotImplementedError

    def clump_per_chr(
        self, sig_df: pd.DataFrame, ldref: str, clump_p1: float, clump_kb: int, clump_r2: float
    ) -> pd.DataFrame:
        """
        LD clumping per chromosome.

        Parameters
        ----------
        sig_df : pd.DataFrame
            The significant snps.
        ldref : str
            The LD reference file, (plink bfile format, containing wildcard {chrom}), e.g. EUR.chr{chrom}.
        clump_p1 : float
            The p1 threshold.
        clump_kb : int
            The kb threshold.
        clump_r2 : float
            The r2 threshold.

        Returns
        -------
        pd.DataFrame
            The clumped snps.
        """
        chrom = sig_df[ColName.CHR].unique()[0]
        sig_df = sig_df[[ColName.SNPID, ColName.P]]
        clump_p_file = self.temp_dir_path / f"clump_p_{chrom}.txt"
        sig_df.to_csv(clump_p_file, sep="\t", index=False)
        clump_outfile = self.temp_dir_path / f"clump_{chrom}.clumped"
        cmd = [
            self.plink,
            "--bfile",
            ldref.format(chrom=chrom),
            "--clump",
            clump_p_file,
            "--clump-p1",
            str(clump_p1),
            "--clump-kb",
            str(clump_kb),
            "--clump-r2",
            str(clump_r2),
            "--clump-snp-field",
            ColName.SNPID,
            "--clump-field",
            ColName.P,
            "--out",
            f"{self.temp_dir}/clump_{chrom}",
        ]
        res = run(cmd, stdout=PIPE, stderr=PIPE, universal_newlines=True)
        if res.returncode != 0:
            self.logger.error(res.stderr)
            raise RuntimeError(res.stderr)
        # else:
        #     clump_df = pd.read_csv(clump_outfile, sep="\t")
        #     clump_df = clump_df[[ColName.SNPID, ColName.P]]
        #     return clump_df

    @staticmethod
    def indep_snps_by_conditional(sig_df: pd.DataFrame, ld_df: pd.DataFrame, r2_threshold: float = 0.8) -> pd.DataFrame:
        """Identify the independent snps by conditional analysis."""
        raise NotImplementedError

    @staticmethod
    def leadsnp2loci(sig_df: pd.DataFrame, range: int = 500000, if_merge: bool = True) -> pd.DataFrame:
        """
        Expand the independent lead snps to independent loci by given range.

        Parameters
        ----------
        sig_df : pd.DataFrame
            The independent lead snps.
        range : int, optional
            The range, by default 1000000
        if_merge : bool, optional
            Whether merge the overlapped loci, by default True

        Returns
        -------
        pd.DataFrame
            The independent loci.
        """
        loci_df = sig_df.copy()
        loci_df = make_SNPID_unique(loci_df)
        loci_df = loci_df[[ColName.CHR, ColName.BP, ColName.P, ColName.SNPID]]
        loci_df.columns = [ColName.CHR, ColName.LEAD_SNP_BP, ColName.LEAD_SNP_P, ColName.LEAD_SNP]  # type: ignore
        loci_df[ColName.START] = loci_df[ColName.LEAD_SNP_BP] - range
        loci_df[ColName.START] = loci_df[ColName.START].apply(lambda x: 0 if x < 0 else x)
        loci_df[ColName.END] = loci_df[ColName.LEAD_SNP_BP] + range
        loci_df = loci_df[ColName.loci_cols].copy()
        if if_merge:
            loci_df = Loci.merge_overlapped_loci(loci_df)
        return loci_df
