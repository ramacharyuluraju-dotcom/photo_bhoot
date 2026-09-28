import streamlit as st
import io
import pandas as pd
from datetime import datetime
from PIL import Image, ImageOps
from supabase import create_client, Client

# ==========================================
# 1. SETUP & CONFIGURATION
# ==========================================
st.set_page_config(page_title="Student Photo Portal", page_icon="📸", layout="centered")

# 🟢 SECRET ADMIN PIN (Change this to whatever you want)
ADMIN_PIN = "9999"

@st.cache_resource
def init_connection():
    url = st.secrets.get("supabase", {}).get("url", "YOUR_SUPABASE_URL")
    key = st.secrets.get("supabase", {}).get("key", "YOUR_SUPABASE_KEY")
    return create_client(url, key)

try:
    supabase: Client = init_connection()
except Exception:
    st.warning("⚠️ Database connection failed. Check your secrets.")
    st.stop()

# Initialize session state for authentication
if 'student_auth' not in st.session_state:
    st.session_state.student_auth = False
    st.session_state.is_admin = False
    st.session_state.student_usn = ""
    st.session_state.student_name = ""
    st.session_state.upload_count = 0

# ==========================================
# 2. IMAGE PROCESSING ENGINE ("The Washing Machine")
# ==========================================
def process_passport_photo(uploaded_file):
    """Converts, center-crops to 3:4 ratio, resizes to 600x800, and compresses to JPG."""
    try:
        img = Image.open(uploaded_file)
        if img.mode != 'RGB': img = img.convert('RGB')
            
        target_size = (600, 800)
        img_cropped = ImageOps.fit(img, target_size, method=Image.Resampling.LANCZOS)
        
        output_buffer = io.BytesIO()
        img_cropped.save(output_buffer, format='JPEG', quality=85, optimize=True)
        output_buffer.seek(0)
        
        return output_buffer
    except Exception as e:
        st.error(f"Image processing failed: {e}")
        return None

# ==========================================
# 3. USER INTERFACE & LOGIC
# ==========================================

st.title("📸 AMCEC Official Photo Portal")
st.markdown("Upload your formal passport-size photograph for your Hall Ticket and Academic Records.")

# --- STEP 1: SECURITY GATE ---
if not st.session_state.student_auth and not st.session_state.is_admin:
    st.info("🔒 Please verify your identity to proceed.")
    
    with st.form("auth_form"):
        usn_input = st.text_input("User Name", placeholder="e.g., TMP-EC-001 or 1AM26EC001").strip().upper()
        pin_input = st.text_input("4-Digit PIN", placeholder="Found on your printed application form", type="password").strip()
        
        submitted = st.form_submit_button("Verify Identity", type="primary", use_container_width=True)
        
        if submitted:
            if not usn_input or not pin_input:
                st.error("⚠️ Both fields are required.")
            elif usn_input == "ADMIN" and pin_input == ADMIN_PIN:
                # 🟢 SECRET ADMIN LOGIN TRIGGER
                st.session_state.is_admin = True
                st.rerun()
            else:
                with st.spinner("Verifying records..."):
                    res = supabase.table("master_students").select("usn, admission_number, full_name, photo_pin, photo_upload_count").eq("usn", usn_input).execute()
                    
                    if not res.data:
                        res = supabase.table("master_students").select("usn, admission_number, full_name, photo_pin, photo_upload_count").eq("admission_number", usn_input).execute()
                    
                    if not res.data:
                        st.error("❌ User Name not found in the master database.")
                    else:
                        student_record = res.data[0]
                        db_pin = str(student_record.get('photo_pin', '')).strip()
                        
                        if db_pin and pin_input == db_pin:
                            st.session_state.student_auth = True
                            st.session_state.student_usn = student_record.get('usn') if student_record.get('usn') else student_record.get('admission_number')
                            st.session_state.student_name = student_record['full_name']
                            st.session_state.upload_count = int(student_record.get('photo_upload_count') or 0)
                            st.rerun()
                        else:
                            st.error("❌ Incorrect PIN. Please check your printed application form.")

# --- STEP 2: SECRET ADMIN DASHBOARD ---
elif st.session_state.is_admin:
    st.success("✅ Logged in as Administrator")
    
    if st.button("🚪 Exit Admin Panel"):
        st.session_state.is_admin = False
        st.rerun()
        
    st.markdown("---")
    st.subheader("📊 Live Upload Analytics")
    
    with st.spinner("Fetching live database metrics..."):
        res = supabase.table("master_students").select("usn, full_name, branch_code, photo_upload_count, last_photo_upload").execute()
        df = pd.DataFrame(res.data)
        
        if not df.empty:
            df['photo_upload_count'] = df['photo_upload_count'].fillna(0).astype(int)
            total_students = len(df)
            total_uploaded = len(df[df['photo_upload_count'] > 0])
            total_pending = total_students - total_uploaded
            completion_rate = (total_uploaded / total_students) * 100 if total_students > 0 else 0
            
            # Key Metrics
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Students", total_students)
            col2.metric("Photos Uploaded", total_uploaded)
            col3.metric("Pending Uploads", total_pending)
            col4.metric("Completion Rate", f"{completion_rate:.1f}%")
            
            st.divider()
            
            # Tabular breakdown
            tab1, tab2, tab3 = st.tabs(["📋 Upload Audit Log", "⚠️ Multiple Replacements", "⏳ Pending Students"])
            
            with tab1:
                st.markdown("**Recent Upload Activity**")
                uploaded_df = df[df['photo_upload_count'] > 0].sort_values(by="last_photo_upload", ascending=False)
                uploaded_df.rename(columns={"usn": "USN", "full_name": "Name", "branch_code": "Branch", "photo_upload_count": "Uploads", "last_photo_upload": "Last Upload Time"}, inplace=True)
                st.dataframe(uploaded_df, use_container_width=True, hide_index=True)
                
            with tab2:
                st.markdown("**Students who changed their photo multiple times**")
                suspicious_df = df[df['photo_upload_count'] > 1].sort_values(by="photo_upload_count", ascending=False)
                suspicious_df.rename(columns={"usn": "USN", "full_name": "Name", "photo_upload_count": "Times Replaced"}, inplace=True)
                st.dataframe(suspicious_df[['USN', 'Name', 'Times Replaced']], use_container_width=True, hide_index=True)
                
            with tab3:
                st.markdown("**Students yet to upload a photo**")
                pending_df = df[df['photo_upload_count'] == 0]
                st.dataframe(pending_df[['usn', 'full_name', 'branch_code']], use_container_width=True, hide_index=True)
        else:
            st.warning("No student records found in the database.")


# --- STEP 3: SECURE UPLOAD BOOTH (STUDENT VIEW) ---
elif st.session_state.student_auth:
    st.success(f"✅ Welcome, **{st.session_state.student_name}** (`{st.session_state.student_usn}`)")
    
    if st.button("🚪 Logout / Wrong Student"):
        st.session_state.student_auth = False
        st.session_state.student_usn = ""
        st.rerun()
        
    st.markdown("---")
    st.subheader("Upload Photograph")
    
    if st.session_state.upload_count > 0:
        st.info(f"🔄 You have already uploaded a photo. Uploading a new one will replace your existing formal photo. (Uploads so far: {st.session_state.upload_count})")
        
    st.markdown("""
    **Guidelines:**
    * 👔 Professional attire required.
    * 🟦 Light or solid background.
    * 👤 Face must be clearly visible and centered.
    * 🗜️ **File size must be strictly below 1 MB.**
    """)
    
    uploaded_file = st.file_uploader("Choose a file", type=['jpg', 'jpeg', 'png', 'webp'])
    
    if uploaded_file is not None:
        MAX_FILE_SIZE = 1 * 1024 * 1024  
        
        if uploaded_file.size > MAX_FILE_SIZE:
            current_size_mb = uploaded_file.size / (1024 * 1024)
            st.error(f"❌ **File Too Large!** Your image is {current_size_mb:.2f} MB. Please compress the image to under 1 MB and try again.")
        else:
            st.info("⚙️ Processing image (auto-cropping and optimizing)...")
            processed_bytes = process_passport_photo(uploaded_file)
            
            if processed_bytes:
                st.image(processed_bytes, caption="Final Portrait Preview", width=250)
                
                if st.button("☁️ Confirm & Upload to Database", type="primary", use_container_width=True):
                    with st.spinner("Uploading securely..."):
                        file_name = f"{st.session_state.student_usn}.jpg"
                        try:
                            # Push to Storage Bucket
                            res = supabase.storage.from_("StakeHolders_Photos").upload(
                                file=processed_bytes.getvalue(),
                                path=file_name,
                                file_options={"content-type": "image/jpeg", "upsert": "true"}
                            )
                            
                            # 🟢 UPDATE AUDIT COUNTER IN DATABASE
                            new_count = st.session_state.upload_count + 1
                            supabase.table("master_students").update({
                                "photo_upload_count": new_count,
                                "last_photo_upload": datetime.now().isoformat()
                            }).eq("usn", st.session_state.student_usn).execute()
                            
                            st.session_state.upload_count = new_count
                            
                            st.success("🎉 **Success!** Your photo has been officially updated.")
                            st.balloons()
                        except Exception as e:
                            if "Duplicate" in str(e):
                                # Push replacement to Storage Bucket
                                supabase.storage.from_("StakeHolders_Photos").update(
                                    file=processed_bytes.getvalue(),
                                    path=file_name,
                                    file_options={"content-type": "image/jpeg"}
                                )
                                
                                # 🟢 UPDATE AUDIT COUNTER IN DATABASE
                                new_count = st.session_state.upload_count + 1
                                supabase.table("master_students").update({
                                    "photo_upload_count": new_count,
                                    "last_photo_upload": datetime.now().isoformat()
                                }).eq("usn", st.session_state.student_usn).execute()
                                
                                st.session_state.upload_count = new_count
                                
                                st.success("🎉 **Success!** Your existing photo has been successfully replaced.")
                                st.balloons()
                            else:
                                st.error(f"❌ Upload failed: {e}")
