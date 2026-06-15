"""
Main FastAPI Backend: Voice-to-Invoice order processing pipeline.
Orchestrates audio transcription, AI parsing, inventory management, and order persistence.
"""

import os
import io
import uuid
import tempfile
import subprocess
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv
import speech_recognition as sr
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import (
    initialize_database,
    get_engine,
    get_session_factory,
    Product,
    Order,
    get_product_by_name,
)
from ai_engine import parse_transcript_to_json, configure_gemini_api

# Load environment variables from .env file
load_dotenv()

# Configuration

GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
if not GOOGLE_API_KEY:
    raise RuntimeError(
        "ERROR: GOOGLE_API_KEY environment variable not set.\n"
        "Get a free API key at: https://ai.google.dev\n"
        "Set it with: export GOOGLE_API_KEY='your-key-here'"
    )

GST_RATE: float = 0.18  # 18% GST for Indian B2B transactions


# FastAPI App Initialization


app = FastAPI(
    title="Hinglish Voice-to-Invoice System",
    description="B2B ordering via mixed-language (Hinglish) voice transcription",
    version="1.0.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database and AI initialization
engine = get_engine()
SessionLocal = get_session_factory(engine)


@app.on_event("startup")
async def startup_event() -> None:
    """
    Initialize database and AI engine on application startup.
    Runs once when FastAPI server starts.
    """
    print("\n" + "="*70)
    print("HINGLISH VOICE-TO-INVOICE SYSTEM - STARTUP")
    print("="*70)
    
    try:
        # Initialize database and seed products
        initialize_database()
        
        # Configure Gemini API
        configure_gemini_api(GOOGLE_API_KEY)
        
        print("[STARTUP]  All systems initialized successfully\n")
    
    except Exception as e:
        print(f"[STARTUP]  CRITICAL ERROR: {str(e)}")
        raise



# Helper Functions

def transcribe_audio_to_text(audio_bytes: bytes) -> str:
    """
    Transcribe audio bytes to text using Google Web Speech API (free).
    Handles WebM, WAV, and other audio formats.
    
    Args:
        audio_bytes: Raw audio data (from browser MediaRecorder, typically WebM)
        
    Returns:
        Transcribed text from audio
        
    Raises:
        ValueError: If audio transcription fails
    """
    recognizer = sr.Recognizer()
    tmp_audio_path = None
    
    try:
        # Save audio bytes to temp file with proper extension
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_audio:
            tmp_audio.write(audio_bytes)
            tmp_audio_path = tmp_audio.name
        
        # Try to convert WebM to WAV using ffmpeg via command line
        wav_path = tmp_audio_path.replace(".webm", ".wav")
        
        import subprocess
        result = subprocess.run(
            ["ffmpeg", "-i", tmp_audio_path, "-acodec", "pcm_s16le", "-ar", "16000", wav_path, "-y"],
            capture_output=True,
            timeout=30
        )
        
        if result.returncode == 0 and os.path.exists(wav_path):
            # Successfully converted, use WAV file
            print(f"[AUDIO] WebM -> WAV conversion successful")
            try:
                with sr.AudioFile(wav_path) as source:
                    audio_data = recognizer.record(source)
                # Try English (India) first for better Hinglish support, fallback to Hindi
                try:
                    transcript: str = recognizer.recognize_google(audio_data, language="en-IN")
                except:
                    transcript: str = recognizer.recognize_google(audio_data, language="hi-IN")
                print(f"[AUDIO] Transcription successful: {transcript[:100]}...")
                return transcript
            finally:
                if os.path.exists(wav_path):
                    os.unlink(wav_path)
        else:
            print(f"[AUDIO] ffmpeg conversion failed, trying direct recognition...")
            # Fallback: Try loading raw bytes as audio
            audio_file = io.BytesIO(audio_bytes)
            with sr.AudioFile(audio_file) as source:
                audio_data = recognizer.record(source)
            # Try English (India) first for better Hinglish support, fallback to Hindi
            try:
                transcript: str = recognizer.recognize_google(audio_data, language="en-IN")
            except:
                transcript: str = recognizer.recognize_google(audio_data, language="hi-IN")
            print(f"[AUDIO] Transcription successful (fallback): {transcript[:100]}...")
            return transcript
    
    except sr.UnknownValueError:
        raise ValueError("Could not understand audio. Please speak clearly in Hinglish.")
    
    except sr.RequestError as e:
        raise ValueError(f"Speech recognition service error: {str(e)}")
    
    except Exception as e:
        print(f"[AUDIO] Error: {str(e)}")
        raise ValueError(f"Audio transcription failed: {str(e)}")
    
    finally:
        if tmp_audio_path and os.path.exists(tmp_audio_path):
            os.unlink(tmp_audio_path)


def process_order_items(
    items: List[Dict[str, Any]],
    session: Session
) -> tuple[List[Dict[str, Any]], float]:
    """
    Cross-reference AI-parsed items against product catalog.
    Calculate prices, adjust inventory, and build final invoice.
    
    Args:
        items: List of parsed items from AI with item_name and quantity
        session: Active database session
        
    Returns:
        Tuple of (processed_items_array, total_amount_with_gst)
        
    Raises:
        ValueError: If items cannot be matched or inventory insufficient
    """
    processed_items: List[Dict[str, Any]] = []
    subtotal_inr: float = 0.0
    
    try:
        for item_request in items:
            item_name: str = item_request.get("item_name", "").strip()
            quantity: int = int(item_request.get("quantity", 1))
            
            if quantity <= 0:
                print(f"[ORDER]  Skipping invalid quantity {quantity} for {item_name}")
                continue
            
            # Find product in catalog
            product: Optional[Product] = get_product_by_name(session, item_name)
            
            if not product:
                print(f"[ORDER]  Product not found: {item_name}")
                continue
            
            # Check stock availability
            if product.stock_qty < quantity:
                print(
                    f"[ORDER]  Insufficient stock for {product.product_name}: "
                    f"requested={quantity}, available={product.stock_qty}"
                )
                # Still process but note limitation
                quantity = product.stock_qty
            
            # Calculate line item total
            line_total: float = product.unit_price_inr * quantity
            subtotal_inr += line_total
            
            # Update inventory
            product.stock_qty -= quantity
            session.add(product)
            
            # Add to processed items
            processed_items.append({
                "product_id": product.product_id,
                "item_name": product.product_name,
                "brand": product.brand,
                "unit_price_inr": product.unit_price_inr,
                "quantity": quantity,
                "line_total_inr": line_total,
            })
            
            print(f"[ORDER]  {product.product_name} x{quantity} @ ₹{product.unit_price_inr} = ₹{line_total}")
        
        # Calculate GST and final total
        gst_amount: float = subtotal_inr * GST_RATE
        total_amount_inr: float = subtotal_inr + gst_amount
        
        print(f"[ORDER] Subtotal: ₹{subtotal_inr:.2f} | GST (18%): ₹{gst_amount:.2f} | Total: ₹{total_amount_inr:.2f}")
        
        return processed_items, total_amount_inr
    
    except Exception as e:
        session.rollback()
        print(f"[ORDER] ERROR during item processing: {str(e)}")
        raise ValueError(f"Failed to process order items: {str(e)}") from e



# API Endpoints


@app.get("/api/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "service": "Hinglish Voice-to-Invoice System",
        "version": "1.0.0",
    }


@app.post("/api/order/process-voice")
async def process_voice_order(
    audio_file: UploadFile = File(..., description="Audio file (WAV/WebM)"),
    customer_name: str = "Default Customer",
) -> Dict[str, Any]:
    """
    Main endpoint: Process voice recording -> Transcribe -> Parse -> Save Order.
    
    Args:
        audio_file: Multipart form audio file upload
        customer_name: Optional customer identifier
        
    Returns:
        JSON response with order details and invoice
        
    Response Schema:
        {
            "status": "success" | "error",
            "order_id": "uuid-string",
            "transcript_extracted": "transcribed text",
            "items_ordered": [...],
            "subtotal_inr": float,
            "gst_inr": float,
            "total_amount_inr": float,
            "message": "descriptive message"
        }
    """
    
    session: Session = SessionLocal()
    
    try:
        print(f"\n[ENDPOINT] Starting voice order processing...")
        
        # Step 1: Read audio bytes
        audio_bytes: bytes = await audio_file.read()
        
        if not audio_bytes:
            raise ValueError("Audio file is empty")
        
        print(f"[ENDPOINT] Received audio file: {len(audio_bytes)} bytes")
        
        # Step 2: Transcribe audio to text
        transcript_text: str = transcribe_audio_to_text(audio_bytes)
        
        if not transcript_text.strip():
            raise ValueError("Transcribed text is empty")
        
        print(f"[ENDPOINT] Transcript: '{transcript_text}'")
        
        # Step 3: Parse transcript to structured JSON using Gemini AI
        parsed_items: List[Dict[str, Any]] = parse_transcript_to_json(
            transcript_text,
            api_key=GOOGLE_API_KEY
        )
        
        if not parsed_items:
            print("[ENDPOINT] No items recognized from transcript")
            return {
                "status": "warning",
                "order_id": str(uuid.uuid4()),
                "transcript_extracted": transcript_text,
                "items_ordered": [],
                "subtotal_inr": 0.0,
                "gst_inr": 0.0,
                "total_amount_inr": 0.0,
                "message": "No items recognized from voice transcript",
            }
        
        # Step 4: Process items and calculate total
        processed_items, total_with_gst = process_order_items(parsed_items, session)
        
        if not processed_items:
            session.rollback()
            return {
                "status": "warning",
                "order_id": str(uuid.uuid4()),
                "transcript_extracted": transcript_text,
                "items_ordered": [],
                "subtotal_inr": 0.0,
                "gst_inr": 0.0,
                "total_amount_inr": 0.0,
                "message": "Parsed items do not match catalog",
            }
        
        # Step 5: Create order record
        order_id: str = str(uuid.uuid4())
        subtotal: float = sum(item["line_total_inr"] for item in processed_items)
        gst_amount: float = subtotal * GST_RATE
        
        import json
        order = Order(
            order_id=order_id,
            customer_name=customer_name,
            items_json=json.dumps(processed_items, ensure_ascii=False),
            total_amount=total_with_gst,
        )
        
        session.add(order)
        session.commit()
        
        print(f"[ENDPOINT] Order saved: {order_id}")
        
        # Step 6: Return success response
        return {
            "status": "success",
            "order_id": order_id,
            "transcript_extracted": transcript_text,
            "items_ordered": processed_items,
            "subtotal_inr": round(subtotal, 2),
            "gst_inr": round(gst_amount, 2),
            "total_amount_inr": round(total_with_gst, 2),
            "message": f"Order {order_id} created successfully",
        }
    
    except ValueError as e:
        print(f"[ENDPOINT] Validation error: {str(e)}")
        session.rollback()
        
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "message": str(e),
                "error_type": "validation_error",
            }
        )
    
    except Exception as e:
        print(f"[ENDPOINT] Unexpected error: {str(e)}")
        session.rollback()
        
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "message": "Internal server error during order processing",
                "error_type": "server_error",
            }
        )
    
    finally:
        session.close()


@app.get("/api/products")
async def list_products() -> Dict[str, Any]:
    """Retrieve all available products in catalog."""
    session: Session = SessionLocal()
    
    try:
        products: List[Product] = session.query(Product).all()
        
        return {
            "status": "success",
            "products": [
                {
                    "product_id": p.product_id,
                    "product_name": p.product_name,
                    "brand": p.brand,
                    "unit_price_inr": p.unit_price_inr,
                    "stock_qty": p.stock_qty,
                }
                for p in products
            ],
            "total_count": len(products),
        }
    
    finally:
        session.close()


@app.get("/api/orders/{order_id}")
async def get_order(order_id: str) -> Dict[str, Any]:
    """Retrieve specific order by ID."""
    session: Session = SessionLocal()
    
    try:
        order: Optional[Order] = session.query(Order).filter(
            Order.order_id == order_id
        ).first()
        
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        import json
        items = json.loads(order.items_json)
        
        return {
            "status": "success",
            "order": {
                "order_id": order.order_id,
                "customer_name": order.customer_name,
                "items": items,
                "total_amount_inr": order.total_amount,
                "created_at": order.created_at.isoformat(),
            }
        }
    
    finally:
        session.close()


# Serve static files and index.html
@app.get("/")
async def serve_root() -> FileResponse:
    """Serve the web UI from index.html"""
    return FileResponse("index.html")


if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "="*70)
    print("Starting Hinglish Voice-to-Invoice FastAPI Server")
    print("="*70)
    print("API Documentation: http://localhost:8000/docs")
    print("="*70 + "\n")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
