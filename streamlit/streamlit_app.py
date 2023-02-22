import mols2grid
from rdkit import Chem
from rdkit import DataStructs
from prolif.plotting.network import LigNetwork
import prolif as plf
import MDAnalysis as mda
import numpy as np
import streamlit as st
import tempfile
import streamlit.components.v1 as components
from moldrug import utils
from meeko import RDKitMolCreate, PDBQTMolecule
from io import StringIO
import seaborn as sns
import matplotlib.pyplot as plt
import pandas as pd
import py3Dmol
from stmol import showmol
import os
import pubchempy as pcp
import requests
import time

from pandas.api.types import (
    is_categorical_dtype,
    is_datetime64_any_dtype,
    is_numeric_dtype,
    is_object_dtype,
)

# TODO
# add SyGma for metabolic prediction
# add prediction of synthetic routes.
# st.set_page_config('wide')
st.sidebar.empty()
st.title('Dashboard')
st.image('https://github.com/ale94mleon/MolDrug/raw/main/docs/source/_static/logo.png?raw=true', width=150)

with st.expander('**About the App**'):
    st.markdown("👈 Open the side bar to introduce the data.\n\n"\
        "This app is to get an overview of a Moldrug result at glance."
        "Check this [flash tutorial](https://moldrug.readthedocs.io/en/latest/source/moldrug_dahsboard.html) in case you get stock on how to use the app; "
        "or [MolDrug's docs](https://moldrug.rtfd.io/) and [MolDrug's GitHub](https://github.com/ale94mleon/moldrug/) for more information.")

tab1, tab2, tab3, tab4 = st.tabs(["Molecules", "Running info","Ligand-protein network interaction overview", "Compound Vendors"])


@st.cache_data
def convert_df(df):
   return df.to_csv().encode('utf-8')

def filter_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Take it from: https://blog.streamlit.io/auto-generate-a-dataframe-filtering-ui-in-streamlit-with-filter_dataframe/
    Adds a UI on top of a dataframe to let viewers filter columns

    Args:
        df (pd.DataFrame): Original dataframe

    Returns:
        pd.DataFrame: Filtered dataframe
    """
    modify = st.checkbox("Add filters")

    if not modify:
        return df

    df = df.copy()

    # Try to convert datetimes into a standard format (datetime, no timezone)
    for col in df.columns:
        if is_object_dtype(df[col]):
            try:
                df[col] = pd.to_datetime(df[col])
            except Exception:
                pass

        if is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.tz_localize(None)

    modification_container = st.container()

    with modification_container:
        to_filter_columns = st.multiselect("Filter dataframe on", df.columns)
        for column in to_filter_columns:
            _, right = st.columns((1, 20))
            # Treat columns with < 10 unique values as categorical
            if is_categorical_dtype(df[column]) or df[column].nunique() < 10:
                user_cat_input = right.multiselect(
                    f"Values for {column}",
                    df[column].unique(),
                    default=list(df[column].unique()),
                )
                df = df[df[column].isin(user_cat_input)]
            elif is_numeric_dtype(df[column]):
                _min = float(df[column].min())
                _max = float(df[column].max())
                step = (_max - _min) / 100
                user_num_input = right.slider(
                    f"Values for {column}",
                    min_value=_min,
                    max_value=_max,
                    value=(_min, _max),
                    step=step,
                )
                df = df[df[column].between(*user_num_input)]
            elif is_datetime64_any_dtype(df[column]):
                user_date_input = right.date_input(
                    f"Values for {column}",
                    value=(
                        df[column].min(),
                        df[column].max(),
                    ),
                )
                if len(user_date_input) == 2:
                    user_date_input = tuple(map(pd.to_datetime, user_date_input))
                    start_date, end_date = user_date_input
                    df = df.loc[df[column].between(start_date, end_date)]
            else:
                user_text_input = right.text_input(
                    f"Substring or regex in {column}",
                )
                if user_text_input:
                    df = df[df[column].astype(str).str.contains(user_text_input)]

    return df


def MolFromPdbqtBlock(pdbqt_string):
    pdbqt_tmp = tempfile.NamedTemporaryFile(suffix='.pdbqt')
    with open(pdbqt_tmp.name, 'w') as f:
        f.write(pdbqt_string)
    pdbqt_mol = PDBQTMolecule.from_file(pdbqt_tmp.name, skip_typing=True)
    mol = RDKitMolCreate.from_pdbqt_mol(pdbqt_mol)[0]
    return mol

#TODO use the selection of the table and download The docking pose storage in the Individual
# Or something like make_sdf of moldrug and download the info
# Another tab that print the general information how went the rum print some convergency
# The violin plot

def convert(number):
    if isinstance(number, np.floating):
        return float(number)
    if isinstance(number, np.integer):
        return int(number)

def plot_dist(individuals:list[utils.Individual], properties:list[str], every_gen:int = 1):
    """Create the violin plot for the MolDrug run

    Parameters
    ----------
    individuals : list[utils.Individual]
        A list of individuals
    properties : list[str]
        A list of the properties to be graph (must be attributes of the provided individuals)
    every_gen : int, optional
        Frequency to plot the distribution: every how many generations, by default 1

    Returns
    -------
    tuple
        fig, axes
    """


    # Set up the matplotlib figure
    sns.set_theme(style="whitegrid")
    fig, axes = plt.subplots(nrows = len(properties), figsize=(25, 25))

    SawIndividuals = utils.to_dataframe(individuals).drop(['pdbqt'], axis = 1).replace([np.inf, -np.inf], np.nan).dropna()
    SawIndividuals = SawIndividuals[SawIndividuals['kept_gens'].map(len) != 0].reset_index(drop=True)
    gen_idxs = sorted(SawIndividuals.genID.unique())
    NumGens = max(gen_idxs)

    # Set pop to the initial population and pops out the first gen
    pop = SawIndividuals[SawIndividuals.genID == gen_idxs.pop(0)].sort_values(by=["cost"])
    pops = pop.copy()
    for gen_idx in gen_idxs:
        idx = [i for i in range(SawIndividuals.shape[0]) if gen_idx in SawIndividuals.loc[i,'kept_gens']]
        pop = SawIndividuals.copy().iloc[idx,:].assign(genID=gen_idx)
        pops = pd.concat([pops, pop.copy()])
    # Draw a violinplot with a narrow bandwidth than the default
    pops = pops.loc[pops['genID'].isin([gen for gen in range(0, NumGens+every_gen, every_gen)])]

    if len(properties) <= 1:
        sns.violinplot(x = 'genID', y = properties[0], data=pops, palette="Set3", bw=.2, cut=0, linewidth=1, ax=axes)
    else:
        for i, prop in enumerate(properties):
            sns.violinplot(x = 'genID', y = prop, data=pops, palette="Set3", bw=.2, cut=0, linewidth=1, ax=axes[i])

    return fig, axes

@st.cache_data
def ProtPdbBlockToProlifMol(protein_pdb_string):
    with tempfile.NamedTemporaryFile(prefix='.pro', suffix='.pdb', mode='w+') as tmp:
        tmp.write(protein_pdb_string)
        protein = mda.Universe(tmp.name)
        protein = plf.Molecule.from_mda(protein)
    return protein

@st.cache_data
def LigPdbqtBlockToProlifMol(ligand_pdbqt_string):
    ligand = MolFromPdbqtBlock(ligand_pdbqt_string)
    ligand = plf.Molecule.from_rdkit(ligand)
    return ligand

@st.cache_data
def prolif_plot(ligand_pdbqt_string,protein_pdb_string):

    # ProLIF example
    # load topology
    # Protein
    protein = ProtPdbBlockToProlifMol(protein_pdb_string)
    ligand = LigPdbqtBlockToProlifMol(ligand_pdbqt_string)

    fp = plf.Fingerprint()
    fp.run_from_iterable([ligand], protein)
    df_fp = fp.to_dataframe(return_atoms=True)

    net = LigNetwork.from_ifp(
        df_fp,
        ligand,
        # replace with `kind="frame", frame=0` for the other depiction
        kind="aggregate",
        threshold=0.3,
        rotation=270,
    )

    prolif_ligplot_html_document = net.display(height="400px").data
    return prolif_ligplot_html_document

@st.cache_data
def lig_prot_overview(_pop, protein_pdb_string):
    protein = ProtPdbBlockToProlifMol(protein_pdb_string)
    with tempfile.NamedTemporaryFile(mode='w+') as tmp:
        utils.make_sdf(_pop, tmp.name)
        directory, name = os.path.split(tmp.name)
        lig_suppl = plf.sdf_supplier(os.path.join(directory, f"{name}.sdf"))
    # generate fingerprint
    fp = plf.Fingerprint()
    fp.run_from_iterable(lig_suppl, protein)
    df = fp.to_dataframe()
    df = df.droplevel("ligand", axis=1)

    # aminoacids = set()
    # interaction_types = set()
    # for aminoacid, interaction_type in df.columns:
    #     aminoacids.add(aminoacid)
    #     interaction_types.add(interaction_type)
    # aminoacids = sorted(aminoacids)
    # interaction_types = sorted(interaction_types)

    df.index = [individual.idx for individual in _pop]
    df.index.names = ['idx']


    # # show all interactions with a specific protein residue
    # df = df.xs("TYR31.A", level="protein", axis=1)
    # show all pi-stacking interactions
    # df = df.xs(interaction_types[0], level="interaction", axis=1)
    return df

def py3Dmol_plot(ligand_pdbqt_string,protein_pdb_string, spin = False):

    ligand = MolFromPdbqtBlock(ligand_pdbqt_string)
    view = py3Dmol.view()
    view.removeAllModels()
    view.setViewStyle({'style':'outline','color':'black','width':0.1})

    view.addModel(protein_pdb_string,format='pdb')
    Prot=view.getModel()
    Prot.setStyle({'cartoon':{'arrows':True, 'tubes':True, 'style':'oval', 'color':'white'}})
    view.addSurface(py3Dmol.VDW,{'opacity':0.6,'color':'white'})

    view.addModel(Chem.MolToMolBlock(ligand),format='mol2')
    ref_m = view.getModel()
    ref_m.setStyle({},{'stick':{'colorscheme':'greenCarbon','radius':0.2}})
    if spin:
        view.spin(True)
    else:
        view.spin(False)
    view.zoomTo()
    showmol(view,height=500,width=800)


@st.cache_data
def load_pbz2(pbz2):
    moldrug_result = utils.decompress_pickle(pbz2)
    if isinstance(moldrug_result, utils.GA):
        gen, pop = moldrug_result.NumGens, moldrug_result.pop
    elif isinstance(moldrug_result, utils.Local):
        gen, pop = 0, moldrug_result.pop
    elif isinstance(moldrug_result, tuple):
        if isinstance(moldrug_result[0], int) and isinstance(moldrug_result[1][0], utils.Individual):
            gen, pop = moldrug_result[0], moldrug_result[1]
    else:
        raise Exception('pbz2 is corrupted')


    try:
        dataframe = utils.to_dataframe(pop, return_mol = True)
    except TypeError:
        dataframe = utils.to_dataframe(pop)
    pdbqt_dataframe = dataframe[['idx','pdbqt']]
    pdbqt_dataframe.set_index('idx', inplace=True)
    return gen, moldrug_result, pdbqt_dataframe, dataframe

@st.cache_data
def upload_file_to_string(uploaded_file):
    # To convert to a string based IO:
    stringio = StringIO(uploaded_file.getvalue().decode("utf-8"))
    # To read file as string:
    string_data = stringio.read()
    return string_data

# PubChem functions
def get_similarity(smiles1:str, smiles2:str) -> float:
    """Get the similarity between two molecules

    Parameters
    ----------
    smiles1 : str
        The SMILES representation of the first molecule
    smiles2 : str
        The SMILES representation of the second molecule

    Returns
    -------
    float
        Similarity
    """
    # Convert SMILES strings to RDKit molecules
    mol1 = Chem.MolFromSmiles(smiles1)
    mol2 = Chem.MolFromSmiles(smiles2)

    # Calculate fingerprints for each molecule

    fp1 = Chem.RDKFingerprint(mol1)
    fp2 = Chem.RDKFingerprint(mol2)
    
    # Calculate similarity
    similarity = DataStructs.FingerprintSimilarity(fp1, fp2)
    
    return similarity


def get_compound_vendors(cid:int) -> tuple:
    """Gte the vendors of the molecule with CID in PubChem

    Parameters
    ----------
    cid : int
        Compound Identification in PubChem

    Returns
    -------
    tuple
        (vendor URL; number of vendors)
    """
    url = f'https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/categories/compound/{cid}/JSON'

    response = requests.get(url)

    data = response.json()
    if 'SourceCategories' in data:
        num_sources = len(data['SourceCategories']['Categories'])
        vendor_url = data['SourceCategories']['Categories'][0]['URL']
        return vendor_url, num_sources
    else:
        return None, 0

def get_pubchem_data(smiles:str, Threshold:int = 95) -> dict:
    """Get the data from PubChem

    Parameters
    ----------
    smiles : str
        The SMILES identification
    Threshold : int, optional
        Threshold of similarity in case that the molecule is not in PubChem, by default 95

    Returns
    -------
    dict
        A dictionary with keywords: smiles, cid, similarity, vendors_link, num_vendors
    """
    result = {
        'smiles': None,
        'cid': None,
        'similarity': None,
        'vendors_link':None,
        'num_vendors': 0,
        
    }
    num_iter = 1
    onsimilarity = False
    for i in range(num_iter):
        try:
            if not onsimilarity:
                compound = pcp.get_compounds(
                    identifier = smiles,
                    namespace='smiles',
                    domain='compound')[0]
                if compound.cid:
                    vendors_link, num_vendors = get_compound_vendors(compound.cid)
                    result.update({
                        'smiles': smiles,
                        'cid': compound.cid,
                        'similarity': 1,
                        'vendors_link': vendors_link,
                        'num_vendors': num_vendors,
                    })
                    break
                else:
                    onsimilarity = True
            if onsimilarity:
                compound = pcp.get_compounds(
                    identifier = smiles,
                    namespace='smiles',
                    domain='compound',
                    searchtype='similarity',
                    Threshold = Threshold,
                    MaxRecords=1)[0]
                if compound.cid:
                    vendors_link, num_vendors = get_compound_vendors(compound.cid)
                    result.update({
                        'smiles': compound.isomeric_smiles,
                        'cid': compound.cid,
                        'similarity': get_similarity(smiles, compound.isomeric_smiles),
                        'vendors_link': vendors_link,
                        'num_vendors': num_vendors,
                    })
                    break
        except pcp.PubChemHTTPError as e:
            if e.msg == 'PUGREST.ServerBusy':
                time.sleep(3)
                if i == num_iter - 1:
                    result.update({'cid': e.msg})
            else:
                result.update({'cid': e.msg})
                break

    return result

@st.cache_data
def get_pubchem_dataframe(df:pd.DataFrame) -> pd.DataFrame:
    """It calls get_pubchem_data on each smiles of df and return
    a DataFrame

    Parameters
    ----------
    df : pd.DataFrame
        With columns: idx (the identification used in MolDrug) and smiles (the SMILES of the molecule)

    Returns
    -------
    pd.DataFrame
        _description_
    """
    data = []
    for _, row in df.iterrows():
        new_row = get_pubchem_data(smiles=row['smiles'])
        new_row['idx'] = row['idx']
        data.append(new_row)
    return pd.DataFrame(data)[['idx', 'cid', 'similarity', 'smiles', 'num_vendors', 'vendors_link']]

    # data = []
    # with concurrent.futures.ThreadPoolExecutor() as executor:
    #     future_to_row = {executor.submit(get_pubchem_data, row['smiles']): row for _, row in df.iterrows()}
    #     for future in concurrent.futures.as_completed(future_to_row):
    #         row = future_to_row[future]
    #         new_row = future.result()
    #         new_row['idx'] = row['idx']
    #         data.append(new_row)
    # return pd.DataFrame(data)[['idx', 'cid', 'similarity', 'smiles', 'num_vendors', 'vendors_link']]


# Upload the data, result and PDB used fopr the docking
st.sidebar.subheader('Upload pbz2:')
# pbz2 = '/home/ale/mnt/snowden2/MolDrug/HIPS/Second/LasB/Cost/free/CH4/replica1/04_local_result.pbz2'
pbz2 = st.sidebar.file_uploader('**MolDrug pbz2**', accept_multiple_files = False)



if pbz2:

    gen, moldrug_result, pdbqt_dataframe, dataframe = load_pbz2(pbz2)
    st.sidebar.write(f"**Loaded generation = {gen}**")
    try:
        dataframe['mol'] = dataframe['mol'].apply(Chem.RemoveHs)
    except KeyError:
        dataframe['mol'] = dataframe['pdbqt'].apply(lambda x: Chem.RemoveHs(MolFromPdbqtBlock(x)))

    properties = [prop for prop in dataframe.columns if prop not in ['idx','pdbqt', 'mol', 'kept_gens']]
    properties = st.sidebar.multiselect(
    "Choose properties", properties, ["cost"]
    )


    # # Plot the prolif and the tridimensional structure with py3Dmol
    # # That two columns


    # Get the minimum and maximum of the variables and used them
    cost_threshold = st.sidebar.slider('**Coloring cost threshold:**', 0.0,1.0,0.5)
    sliders = []
    for prop in properties:
        minimum, maximum = convert(dataframe[prop].min()), convert(dataframe[prop].max())
        sliders.append(st.sidebar.slider(f'**{prop}**', minimum,maximum,[minimum,maximum]))


    grid = mols2grid.MolGrid(
        dataframe,
        mol_col = 'mol',
        # molecule drawing parameters
        fixedBondLength=25,
        clearBackground=False,
        size=(130, 120),
    )

    for prop, slide in zip(properties,sliders):
        grid.dataframe = grid.dataframe[(slide[0]<= grid.dataframe[prop]) & (grid.dataframe[prop]<=slide[1])]

    try:
        view = grid.display(
            # set what's displayed on the grid
            subset=["idx", "img", "cost"],
            # # set what's displayed on the hover tooltip
            tooltip=list(set(["cost",'idx'] + properties)),
            tooltip_placement="auto",
            # style for the grid labels and tooltips
            style={
            "cost": lambda x: "color: red; font-weight: bold;" if x < cost_threshold else "",
            "__all__": lambda x: "background-color: azure;" if x["cost"] >= cost_threshold else ""
            },
            # change the precision and format (or other transformations)
            transform={"cost": lambda x: round(x, 3)},
            # sort the grid in a different order by default
            sort_by="cost",
            n_rows=3,

            callback=mols2grid.callbacks.info(img_size=(200, 150)),
        )

        with tab1:
            components.html(view.data, width=None, height=700, scrolling=True)

    except ValueError:
        with tab1:
            st.info('Nothing to show')


    with tab4:
        PubChemCheck = st.checkbox("Explore PubChem")
        download_button = st.empty()
        if PubChemCheck:
            st.info("Be patient, this could take a while ⌛")
            dataframe = dataframe.copy()
            dataframe['smiles'] = dataframe['mol'].apply(Chem.MolToSmiles)
            pubchem_dataframe = get_pubchem_dataframe(dataframe[['idx', 'smiles']])
            pubchem_dataframe = pubchem_dataframe[pubchem_dataframe['idx'].isin(grid.dataframe['idx'])]
            pubchem_dataframe = pubchem_dataframe.set_index('idx')
            st.dataframe(pubchem_dataframe)
            download_button.download_button(
                "Press to Download",
                convert_df(pubchem_dataframe),
                "PubChemData.csv",
                "text/csv",
                key='download-csv'
                )

    
        
    plif = st.empty()

    st.sidebar.subheader('**Ligand-protein network interaction**')


    # Every form must have a submit button
    protein_pdb = st.sidebar.file_uploader('**Protein PDB**', accept_multiple_files = False)
    if protein_pdb:
        protein_pdb_string=upload_file_to_string(protein_pdb)

        # Get overview
        df_overview = lig_prot_overview(moldrug_result.pop, protein_pdb_string=protein_pdb_string)
        with tab3:
            st.dataframe(filter_dataframe(df_overview[df_overview.index.isin(grid.dataframe['idx'])]))

        # Input widget
        idx = st.sidebar.selectbox('idx', sorted(pdbqt_dataframe.index))
        representation = st.sidebar.selectbox('Representation', ['ProLIF', 'Py3Dmol'])
        spin = st.sidebar.empty()
        if representation == 'ProLIF':
            prolif_ligplot_html_document = prolif_plot(
                ligand_pdbqt_string=pdbqt_dataframe.loc[idx, 'pdbqt'],
                protein_pdb_string=protein_pdb_string,
            )
            with plif:
                with tab1:
                    components.html(prolif_ligplot_html_document,width=None, height=500, scrolling=True)
        else:
            spin = spin.checkbox('Spin', value = False)
            with plif:
                with tab1:
                    py3Dmol_plot(
                        ligand_pdbqt_string=pdbqt_dataframe.loc[idx, 'pdbqt'],
                        protein_pdb_string=protein_pdb_string,
                        spin = spin
                    )
    else:
        st.sidebar.info('☝️ Upload the PDB protein file.')

    # Plot the distribution
    with tab2:
        every_gen = st.number_input("Every how many generations:",min_value=1, max_value=moldrug_result.NumGens, value=10)
        try:
            properties_to_plot = [prop for prop in properties if prop not in ['genID']]
            fig, axes = plot_dist(moldrug_result.SawIndividuals,properties=properties_to_plot, every_gen=every_gen)
            st.pyplot(fig)
        except Exception:
            st.info('Nothing to show. Consider to select some properties in the side bar.')

else:
    st.sidebar.info('☝️ Upload a MolDrug pbz2 file.')
