package ai.closepaw.ui.capsule.voice

import android.content.Context
import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.json.JSONObject
import org.tensorflow.lite.DataType
import org.tensorflow.lite.Interpreter

/**
 * Tiny local-only microWakeWord detector.
 *
 * Raw idle microphone audio never leaves the device. 24 kHz PCM from the shared hands-free
 * recorder is downsampled to 16 kHz, converted to the exact forty-bin TFLite-Micro frontend
 * features used during microWakeWord training, then passed through a stateful quantized streaming
 * CNN. The model/manifest are build assets named wake_word.tflite and wake_word.json.
 */
internal class LocalWakeWordDetector(
    private val context: Context,
) : AutoCloseable {
    companion object {
        const val MODEL_ASSET = "wake_word.tflite"
        const val MANIFEST_ASSET = "wake_word.json"
    }

    var wakeWordLabel: String = "wake word"
        private set

    private var frontend: MicroFrontend? = null
    private var interpreter: Interpreter? = null
    private var inputScale = 1f
    private var inputZeroPoint = 0
    private var outputScale = 1f
    private var outputZeroPoint = 0
    private var inputFrames = 0
    private var cutoff = 0.9f
    private var slidingWindow = 5
    private val pendingFrames = ArrayDeque<FloatArray>()
    private val recentProbabilities = ArrayDeque<Float>()
    private var wakeInput: ByteBuffer? = null
    private var wakeOutput: ByteBuffer? = null

    suspend fun initialize(): Result<Unit> = runCatching {
        val manifest = JSONObject(
            context.assets.open(MANIFEST_ASSET).bufferedReader(Charsets.UTF_8).use { it.readText() }
        )
        wakeWordLabel = manifest.optString("wake_word", "wake word")
        val micro = manifest.getJSONObject("micro")
        require(micro.optInt("feature_step_size", MicroFrontend.STEP_SIZE_MS) == MicroFrontend.STEP_SIZE_MS) {
            "microWakeWord manifest feature_step_size must be ${MicroFrontend.STEP_SIZE_MS} ms"
        }
        cutoff = micro.optDouble("probability_cutoff", 0.9).toFloat()
        slidingWindow = maxOf(
            1,
            micro.optInt(
                "sliding_window_average_size",
                micro.optInt("sliding_window_size", 5),
            ),
        )

        val modelBytes = context.assets.open(MODEL_ASSET).use { it.readBytes() }
        val model = ByteBuffer.allocateDirect(modelBytes.size)
            .order(ByteOrder.nativeOrder())
            .apply {
                put(modelBytes)
                rewind()
            }

        val interp = Interpreter(model, Interpreter.Options().apply { setNumThreads(2) })
        interp.allocateTensors()

        val inputTensor = interp.getInputTensor(0)
        val outputTensor = interp.getOutputTensor(0)
        val inputShape = inputTensor.shape()
        val outputShape = outputTensor.shape()
        require(inputShape.size == 3 && inputShape[0] == 1 && inputShape[2] == MicroFrontend.FEATURE_SIZE) {
            "Unexpected microWakeWord input shape: ${inputShape.joinToString()}"
        }
        require(outputShape.size == 2 && outputShape[0] == 1 && outputShape[1] == 1) {
            "Unexpected microWakeWord output shape: ${outputShape.joinToString()}"
        }
        require(inputTensor.dataType() == DataType.INT8) {
            "microWakeWord input must be INT8, got ${inputTensor.dataType()}"
        }
        require(outputTensor.dataType() == DataType.UINT8) {
            "microWakeWord output must be UINT8, got ${outputTensor.dataType()}"
        }

        inputFrames = inputShape[1]
        val iq = inputTensor.quantizationParams()
        inputScale = iq.scale
        inputZeroPoint = iq.zeroPoint
        val oq = outputTensor.quantizationParams()
        outputScale = oq.scale
        outputZeroPoint = oq.zeroPoint

        val localFrontend = MicroFrontend()
        require(localFrontend.isInitialized) { "microWakeWord frontend failed to initialize" }

        wakeInput = ByteBuffer.allocateDirect(inputFrames * MicroFrontend.FEATURE_SIZE)
            .order(ByteOrder.nativeOrder())
        wakeOutput = ByteBuffer.allocateDirect(1).order(ByteOrder.nativeOrder())
        frontend = localFrontend
        interpreter = interp
        reset()
    }

    /** Feed one 24 kHz mono PCM16 frame. Returns true only after the trained wake model fires. */
    fun accept24k(samples: ShortArray, length: Int = samples.size): Boolean {
        val localFrontend = frontend ?: return false
        val interp = interpreter ?: return false
        val input = wakeInput ?: return false
        val output = wakeOutput ?: return false
        if (length <= 0 || inputFrames <= 0) return false

        val sixteenKhz = downsample24To16(samples, length)
        val frames = localFrontend.processSamples(sixteenKhz)
        if (frames.isEmpty()) return false
        pendingFrames.addAll(frames)

        while (pendingFrames.size >= inputFrames) {
            input.rewind()
            repeat(inputFrames) {
                val featureFrame = pendingFrames.removeFirst()
                for (value in featureFrame) {
                    val quantized = Math.round(value / inputScale) + inputZeroPoint
                    input.put(quantized.coerceIn(-128, 127).toByte())
                }
            }
            input.rewind()
            output.rewind()
            interp.run(input, output)
            output.rewind()

            val raw = output.get().toInt() and 0xFF
            val probability = ((raw - outputZeroPoint) * outputScale).coerceIn(0f, 1f)
            recentProbabilities.addLast(probability)
            while (recentProbabilities.size > slidingWindow) recentProbabilities.removeFirst()

            if (recentProbabilities.size == slidingWindow && recentProbabilities.average() >= cutoff) {
                reset()
                return true
            }
        }
        return false
    }

    fun reset() {
        frontend?.reset()
        runCatching { interpreter?.resetVariableTensors() }
        pendingFrames.clear()
        recentProbabilities.clear()
    }

    /**
     * Exact 3:2 resampler for our fixed twenty-millisecond 24 kHz frames. Odd output samples are
     * linearly interpolated instead of nearest-neighbour decimated; VOICE_RECOGNITION capture is
     * already speech-band-limited, so this is a small and cheap bridge into the 16 kHz wake model.
     */
    private fun downsample24To16(input: ShortArray, length: Int): ShortArray {
        val safeLength = length.coerceAtMost(input.size)
        val groups = safeLength / 3
        if (groups <= 0) return ShortArray(0)
        val out = ShortArray(groups * 2)
        var src = 0
        var dst = 0
        repeat(groups) {
            val a = input[src].toInt()
            val b = input[src + 1].toInt()
            val c = input[src + 2].toInt()
            out[dst] = a.toShort()
            out[dst + 1] = ((b + c) / 2).coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt()).toShort()
            src += 3
            dst += 2
        }
        return out
    }

    override fun close() {
        runCatching { interpreter?.close() }
        interpreter = null
        frontend?.close()
        frontend = null
        wakeInput = null
        wakeOutput = null
        pendingFrames.clear()
        recentProbabilities.clear()
    }
}
